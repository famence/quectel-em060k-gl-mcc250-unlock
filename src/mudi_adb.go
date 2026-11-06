package main

import (
	"bytes"
	"crypto"
	"crypto/md5"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"encoding/binary"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// Linux MIPS ioctl encoding:
// _IOC_SIZEBITS = 13, _IOC_DIRBITS = 3
// _IOC_NONE = 1, _IOC_READ = 2, _IOC_WRITE = 4
func mipsIOC(dir, typ, nr, size uintptr) uintptr {
	return (dir << 29) | (size << 16) | (typ << 8) | nr
}

var (
	USBDEVFS_BULK             = mipsIOC(2|4, 'U', 2, 16)
	USBDEVFS_CLAIMINTERFACE   = mipsIOC(2, 'U', 15, 4)
	USBDEVFS_RELEASEINTERFACE = mipsIOC(2, 'U', 16, 4)
	USBDEVFS_IOCTL            = mipsIOC(2|4, 'U', 18, 12)
	USBDEVFS_CLEAR_HALT       = mipsIOC(2, 'U', 21, 4)
	USBDEVFS_DISCONNECT       = mipsIOC(1, 'U', 22, 0)
)

type usbdevfsBulktransfer struct {
	Ep      uint32
	Len     uint32
	Timeout uint32
	Data    uintptr
}

type usbdevfsIoctl struct {
	Ifno      int32
	IoctlCode int32
	Data      uintptr
}

const (
	A_SYNC = 0x434e5953
	A_CNXN = 0x4e584e43
	A_OPEN = 0x4e45504f
	A_OKAY = 0x59414b4f
	A_CLSE = 0x45534c43
	A_WRTE = 0x45545257
	A_AUTH = 0x48545541

	A_VERSION = 0x01000000
	MAX_DATA  = 4096

	ADB_AUTH_TOKEN        = 1
	ADB_AUTH_SIGNATURE    = 2
	ADB_AUTH_RSAPUBLICKEY = 3
)

type adbMsg struct {
	Command    uint32
	Arg0       uint32
	Arg1       uint32
	DataLength uint32
	DataCheck  uint32
	Magic      uint32
	Data       []byte
}

type adbUSB struct {
	fd    int
	ifnum int
	epIn  uint32
	epOut uint32
}

// Compute Quectel AT+QADBKEY unlock response from 8-digit challenge using MD5-crypt ($1$)
func computeQadbkey(challenge string) string {
	pw := []byte("SH_adb_quectel")
	salt := []byte(strings.TrimSpace(challenge))
	if len(salt) > 8 {
		salt = salt[:8]
	}
	magic := []byte("$1$")

	altCtx := md5.New()
	altCtx.Write(pw)
	altCtx.Write(salt)
	altCtx.Write(pw)
	alt := altCtx.Sum(nil)

	ctx := md5.New()
	ctx.Write(pw)
	ctx.Write(magic)
	ctx.Write(salt)
	for pl := len(pw); pl > 0; pl -= 16 {
		if pl > 16 {
			ctx.Write(alt[:16])
		} else {
			ctx.Write(alt[:pl])
		}
	}
	for i := len(pw); i > 0; i >>= 1 {
		if (i & 1) != 0 {
			ctx.Write([]byte{0})
		} else {
			ctx.Write(pw[:1])
		}
	}
	final := ctx.Sum(nil)

	for i := 0; i < 1000; i++ {
		c1 := md5.New()
		if (i & 1) != 0 {
			c1.Write(pw)
		} else {
			c1.Write(final)
		}
		if i%3 != 0 {
			c1.Write(salt)
		}
		if i%7 != 0 {
			c1.Write(pw)
		}
		if (i & 1) != 0 {
			c1.Write(final)
		} else {
			c1.Write(pw)
		}
		final = c1.Sum(nil)
	}

	const itoa64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
	var out bytes.Buffer
	to64 := func(v uint32, n int) {
		for ; n > 0; n-- {
			out.WriteByte(itoa64[v&0x3f])
			v >>= 6
		}
	}
	to64((uint32(final[0])<<16)|(uint32(final[6])<<8)|uint32(final[12]), 4)
	to64((uint32(final[1])<<16)|(uint32(final[7])<<8)|uint32(final[13]), 4)
	to64((uint32(final[2])<<16)|(uint32(final[8])<<8)|uint32(final[14]), 4)
	to64((uint32(final[3])<<16)|(uint32(final[9])<<8)|uint32(final[15]), 4)
	to64((uint32(final[4])<<16)|(uint32(final[10])<<8)|uint32(final[5]), 4)
	to64(uint32(final[11]), 2)

	res := out.String()
	if len(res) > 15 {
		return res[:15]
	}
	return res
}

func readSysHex(path string) (int, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	s := strings.TrimSpace(string(b))
	v, err := strconv.ParseInt(s, 16, 32)
	return int(v), err
}

func readSysDec(path string) (int, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	s := strings.TrimSpace(string(b))
	v, err := strconv.ParseInt(s, 10, 32)
	return int(v), err
}

func findModemADB() (*adbUSB, error) {
	devs, err := filepath.Glob("/sys/bus/usb/devices/*")
	if err != nil {
		return nil, err
	}
	for _, dev := range devs {
		vid, err := readSysHex(filepath.Join(dev, "idVendor"))
		if err != nil || vid != 0x2c7c {
			continue
		}
		busnum, err := readSysDec(filepath.Join(dev, "busnum"))
		if err != nil {
			continue
		}
		devnum, err := readSysDec(filepath.Join(dev, "devnum"))
		if err != nil {
			continue
		}
		ifdirs, _ := filepath.Glob(filepath.Join(dev, "*:*"))
		for _, ifdir := range ifdirs {
			cls, err1 := readSysHex(filepath.Join(ifdir, "bInterfaceClass"))
			sub, err2 := readSysHex(filepath.Join(ifdir, "bInterfaceSubClass"))
			proto, err3 := readSysHex(filepath.Join(ifdir, "bInterfaceProtocol"))
			if err1 != nil || err2 != nil || err3 != nil {
				continue
			}
			if cls == 0xff && sub == 0x42 && proto == 0x01 {
				ifnum, err := readSysHex(filepath.Join(ifdir, "bInterfaceNumber"))
				if err != nil {
					continue
				}
				var epIn, epOut uint32
				epdirs, _ := filepath.Glob(filepath.Join(ifdir, "ep_*"))
				for _, epdir := range epdirs {
					addr, err := readSysHex(filepath.Join(epdir, "bEndpointAddress"))
					if err != nil {
						continue
					}
					if (addr & 0x80) != 0 {
						epIn = uint32(addr)
					} else {
						epOut = uint32(addr)
					}
				}
				if epIn != 0 && epOut != 0 {
					devPath := fmt.Sprintf("/dev/bus/usb/%03d/%03d", busnum, devnum)
					fd, err := syscall.Open(devPath, syscall.O_RDWR, 0)
					if err != nil {
						return nil, fmt.Errorf("open %s: %v", devPath, err)
					}
					ioctlReq := usbdevfsIoctl{
						Ifno:      int32(ifnum),
						IoctlCode: int32(USBDEVFS_DISCONNECT),
						Data:      0,
					}
					syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), USBDEVFS_IOCTL, uintptr(unsafe.Pointer(&ioctlReq)))

					ifn := uint32(ifnum)
					_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(fd), USBDEVFS_CLAIMINTERFACE, uintptr(unsafe.Pointer(&ifn)))
					if errno != 0 {
						syscall.Close(fd)
						return nil, fmt.Errorf("claim interface %d on %s: %v", ifnum, devPath, errno)
					}
					return &adbUSB{
						fd:    fd,
						ifnum: ifnum,
						epIn:  epIn,
						epOut: epOut,
					}, nil
				}
			}
		}
	}
	return nil, fmt.Errorf("Quectel ADB interface (ff/42/01) not found in /sys/bus/usb/devices")
}

func (u *adbUSB) Close() {
	ifn := uint32(u.ifnum)
	syscall.Syscall(syscall.SYS_IOCTL, uintptr(u.fd), USBDEVFS_RELEASEINTERFACE, uintptr(unsafe.Pointer(&ifn)))
	syscall.Close(u.fd)
}

func (u *adbUSB) bulkTransfer(ep uint32, buf []byte, timeoutMs uint32) (int, error) {
	var ptr uintptr
	if len(buf) > 0 {
		ptr = uintptr(unsafe.Pointer(&buf[0]))
	}
	bt := usbdevfsBulktransfer{
		Ep:      ep,
		Len:     uint32(len(buf)),
		Timeout: timeoutMs,
		Data:    ptr,
	}
	r1, _, errno := syscall.Syscall(syscall.SYS_IOCTL, uintptr(u.fd), USBDEVFS_BULK, uintptr(unsafe.Pointer(&bt)))
	if errno != 0 {
		return int(r1), errno
	}
	return int(r1), nil
}

func checksum(data []byte) uint32 {
	var sum uint32
	for _, b := range data {
		sum += uint32(b)
	}
	return sum
}

func (u *adbUSB) sendMsg(cmd, arg0, arg1 uint32, data []byte) error {
	hdr := make([]byte, 24)
	binary.LittleEndian.PutUint32(hdr[0:4], cmd)
	binary.LittleEndian.PutUint32(hdr[4:8], arg0)
	binary.LittleEndian.PutUint32(hdr[8:12], arg1)
	binary.LittleEndian.PutUint32(hdr[12:16], uint32(len(data)))
	binary.LittleEndian.PutUint32(hdr[16:20], checksum(data))
	binary.LittleEndian.PutUint32(hdr[20:24], cmd^0xffffffff)

	if _, err := u.bulkTransfer(u.epOut, hdr, 5000); err != nil {
		return fmt.Errorf("send hdr: %v", err)
	}
	if len(data) > 0 {
		if _, err := u.bulkTransfer(u.epOut, data, 15000); err != nil {
			return fmt.Errorf("send data: %v", err)
		}
		if len(data)%512 == 0 {
			u.bulkTransfer(u.epOut, []byte{}, 1000)
		}
	}
	return nil
}

func (u *adbUSB) recvMsg(timeoutMs uint32) (*adbMsg, error) {
	hdr := make([]byte, 24)
	for {
		n, err := u.bulkTransfer(u.epIn, hdr, timeoutMs)
		if err != nil {
			return nil, fmt.Errorf("recv hdr: %v", err)
		}
		if n != 24 {
			continue
		}
		m := &adbMsg{
			Command:    binary.LittleEndian.Uint32(hdr[0:4]),
			Arg0:       binary.LittleEndian.Uint32(hdr[4:8]),
			Arg1:       binary.LittleEndian.Uint32(hdr[8:12]),
			DataLength: binary.LittleEndian.Uint32(hdr[12:16]),
			DataCheck:  binary.LittleEndian.Uint32(hdr[16:20]),
			Magic:      binary.LittleEndian.Uint32(hdr[20:24]),
		}
		if m.Command != (m.Magic ^ 0xffffffff) {
			continue
		}
		if m.DataLength > 0 {
			m.Data = make([]byte, m.DataLength)
			read := uint32(0)
			for read < m.DataLength {
				chunk := m.Data[read:]
				nr, err := u.bulkTransfer(u.epIn, chunk, timeoutMs)
				if err != nil {
					return nil, fmt.Errorf("recv payload: %v", err)
				}
				read += uint32(nr)
			}
		}
		return m, nil
	}
}

func encodeAndroidPubKey(pub *rsa.PublicKey) []byte {
	b32 := big.NewInt(1 << 32)
	n0 := new(big.Int).Mod(pub.N, b32)
	n0inv := new(big.Int).ModInverse(n0, b32)
	n0inv.Sub(b32, n0inv)

	r := new(big.Int).Lsh(big.NewInt(1), 2048)
	rr := new(big.Int).Mul(r, r)
	rr.Mod(rr, pub.N)

	buf := make([]byte, 524)
	binary.LittleEndian.PutUint32(buf[0:4], 64)
	binary.LittleEndian.PutUint32(buf[4:8], uint32(n0inv.Uint64()))

	nBytes := pub.N.Bytes()
	for i := 0; i < len(nBytes); i++ {
		buf[8+i] = nBytes[len(nBytes)-1-i]
	}
	rrBytes := rr.Bytes()
	for i := 0; i < len(rrBytes); i++ {
		buf[264+i] = rrBytes[len(rrBytes)-1-i]
	}
	binary.LittleEndian.PutUint32(buf[520:524], uint32(pub.E))
	return buf
}

func (u *adbUSB) connect() error {
	for i := 0; i < 16; i++ {
		m, err := u.recvMsg(150)
		if err != nil {
			break
		}
		if m.Command == A_WRTE || m.Command == A_OKAY {
			u.sendMsg(A_CLSE, m.Arg1, m.Arg0, nil)
		}
	}

	if err := u.sendMsg(A_CNXN, A_VERSION, MAX_DATA, []byte("host::\x00")); err != nil {
		return err
	}
	var privKey *rsa.PrivateKey
	sentSig := false
	for {
		m, err := u.recvMsg(10000)
		if err != nil {
			return err
		}
		if m.Command == A_CNXN {
			return nil
		}
		if m.Command == A_WRTE || m.Command == A_OKAY {
			u.sendMsg(A_CLSE, m.Arg1, m.Arg0, nil)
			continue
		}
		if m.Command == A_CLSE {
			continue
		}
		if m.Command == A_AUTH && m.Arg0 == ADB_AUTH_TOKEN {
			if privKey == nil {
				privKey, err = rsa.GenerateKey(rand.Reader, 2048)
				if err != nil {
					return err
				}
			}
			if !sentSig {
				sig, err := rsa.SignPKCS1v15(rand.Reader, privKey, crypto.SHA1, m.Data)
				if err != nil {
					return err
				}
				if err := u.sendMsg(A_AUTH, ADB_AUTH_SIGNATURE, 0, sig); err != nil {
					return err
				}
				sentSig = true
			} else {
				pubKey := encodeAndroidPubKey(&privKey.PublicKey)
				const b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
				var out bytes.Buffer
				for i := 0; i < len(pubKey); i += 3 {
					rem := len(pubKey) - i
					var v uint32
					v |= uint32(pubKey[i]) << 16
					if rem > 1 {
						v |= uint32(pubKey[i+1]) << 8
					}
					if rem > 2 {
						v |= uint32(pubKey[i+2])
					}
					out.WriteByte(b64[(v>>18)&0x3f])
					out.WriteByte(b64[(v>>12)&0x3f])
					if rem > 1 {
						out.WriteByte(b64[(v>>6)&0x3f])
					} else {
						out.WriteByte('=')
					}
					if rem > 2 {
						out.WriteByte(b64[v&0x3f])
					} else {
						out.WriteByte('=')
					}
				}
				out.WriteString(" root@mudi\x00")
				if err := u.sendMsg(A_AUTH, ADB_AUTH_RSAPUBLICKEY, 0, out.Bytes()); err != nil {
					return err
				}
			}
		}
	}
}

func (u *adbUSB) runShell(cmd string) error {
	localID := uint32(1)
	openData := append([]byte("shell:"+cmd), 0)
	if err := u.sendMsg(A_OPEN, localID, 0, openData); err != nil {
		return err
	}
	var remoteID uint32
	for {
		m, err := u.recvMsg(120000)
		if err != nil {
			return err
		}
		switch m.Command {
		case A_OKAY:
			remoteID = m.Arg0
		case A_WRTE:
			remoteID = m.Arg0
			if len(m.Data) > 0 {
				os.Stdout.Write(m.Data)
			}
			if err := u.sendMsg(A_OKAY, localID, remoteID, nil); err != nil {
				return err
			}
		case A_CLSE:
			u.sendMsg(A_CLSE, localID, remoteID, nil)
			return nil
		}
	}
}

func (u *adbUSB) pullFile(remotePath, localPath string) error {
	localID := uint32(3)
	if err := u.sendMsg(A_OPEN, localID, 0, []byte("sync:\x00")); err != nil {
		return err
	}
	m, err := u.recvMsg(10000)
	if err != nil {
		return err
	}
	if m.Command != A_OKAY {
		return fmt.Errorf("expected OKAY on sync:, got 0x%x", m.Command)
	}
	remoteID := m.Arg0

	var req bytes.Buffer
	req.WriteString("RECV")
	var tmp [4]byte
	binary.LittleEndian.PutUint32(tmp[:], uint32(len(remotePath)))
	req.Write(tmp[:])
	req.WriteString(remotePath)

	if err := u.sendMsg(A_WRTE, localID, remoteID, req.Bytes()); err != nil {
		return err
	}

	outFile, err := os.Create(localPath)
	if err != nil {
		return err
	}
	defer outFile.Close()

	var streamBuf bytes.Buffer
	done := false
	for !done {
		pkt, err := u.recvMsg(30000)
		if err != nil {
			return err
		}
		switch pkt.Command {
		case A_OKAY:
			continue
		case A_WRTE:
			if err := u.sendMsg(A_OKAY, localID, remoteID, nil); err != nil {
				return err
			}
			streamBuf.Write(pkt.Data)
			for streamBuf.Len() >= 8 {
				hdr := streamBuf.Bytes()[:8]
				tag := string(hdr[0:4])
				chunkLen := int(binary.LittleEndian.Uint32(hdr[4:8]))
				if tag == "DONE" {
					streamBuf.Next(8)
					done = true
					break
				} else if tag == "FAIL" {
					if streamBuf.Len() < 8+chunkLen {
						break
					}
					streamBuf.Next(8)
					errMsg := string(streamBuf.Next(chunkLen))
					return fmt.Errorf("sync RECV failed: %s", errMsg)
				} else if tag == "DATA" {
					if streamBuf.Len() < 8+chunkLen {
						break
					}
					streamBuf.Next(8)
					chunk := streamBuf.Next(chunkLen)
					if _, err := outFile.Write(chunk); err != nil {
						return err
					}
				} else {
					return fmt.Errorf("unexpected sync tag: %q", tag)
				}
			}
		case A_CLSE:
			done = true
		}
	}
	u.sendMsg(A_CLSE, localID, remoteID, nil)
	return nil
}

func (u *adbUSB) pushFile(localPath, remotePath string) error {
	data, err := os.ReadFile(localPath)
	if err != nil {
		return err
	}
	localID := uint32(2)
	if err := u.sendMsg(A_OPEN, localID, 0, []byte("sync:\x00")); err != nil {
		return err
	}
	m, err := u.recvMsg(10000)
	if err != nil {
		return err
	}
	if m.Command != A_OKAY {
		return fmt.Errorf("expected OKAY on sync:, got 0x%x", m.Command)
	}
	remoteID := m.Arg0

	sendWrite := func(payload []byte) error {
		for len(payload) > 0 {
			chunk := payload
			if len(chunk) > MAX_DATA {
				chunk = payload[:MAX_DATA]
			}
			payload = payload[len(chunk):]
			if err := u.sendMsg(A_WRTE, localID, remoteID, chunk); err != nil {
				return err
			}
			ack, err := u.recvMsg(10000)
			if err != nil {
				return err
			}
			if ack.Command != A_OKAY {
				return fmt.Errorf("expected OKAY on WRTE, got 0x%x", ack.Command)
			}
		}
		return nil
	}

	spec := fmt.Sprintf("%s,33188", remotePath) // 0100644
	var buf bytes.Buffer
	buf.WriteString("SEND")
	var tmp [4]byte
	binary.LittleEndian.PutUint32(tmp[:], uint32(len(spec)))
	buf.Write(tmp[:])
	buf.WriteString(spec)

	offset := 0
	for offset < len(data) {
		end := offset + 32768
		if end > len(data) {
			end = len(data)
		}
		chunk := data[offset:end]
		buf.WriteString("DATA")
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(chunk)))
		buf.Write(tmp[:])
		buf.Write(chunk)
		offset = end
	}
	buf.WriteString("DONE")
	binary.LittleEndian.PutUint32(tmp[:], uint32(time.Now().Unix()))
	buf.Write(tmp[:])

	if err := sendWrite(buf.Bytes()); err != nil {
		return err
	}

	resp, err := u.recvMsg(10000)
	if err != nil {
		return err
	}
	if resp.Command == A_WRTE {
		u.sendMsg(A_OKAY, localID, remoteID, nil)
		if len(resp.Data) >= 4 && string(resp.Data[:4]) != "OKAY" {
			return fmt.Errorf("sync error: %s", string(resp.Data))
		}
	}
	u.sendMsg(A_CLSE, localID, remoteID, nil)
	return nil
}

var _ = sha1.New

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage:\n  %s <shell-cmd>\n  %s pull <remote> <local>\n  %s push <local> <remote>\n  %s qadbkey <challenge>\n", os.Args[0], os.Args[0], os.Args[0], os.Args[0])
		os.Exit(1)
	}
	if os.Args[1] == "qadbkey" && len(os.Args) == 3 {
		fmt.Println(computeQadbkey(os.Args[2]))
		return
	}

	u, err := findModemADB()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	defer u.Close()

	if err := u.connect(); err != nil {
		fmt.Fprintf(os.Stderr, "ADB connect error: %v\n", err)
		os.Exit(1)
	}

	if os.Args[1] == "pull" && len(os.Args) == 4 {
		if err := u.pullFile(os.Args[2], os.Args[3]); err != nil {
			fmt.Fprintf(os.Stderr, "ADB pull error: %v\n", err)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "Pulled %s -> %s\n", os.Args[2], os.Args[3])
		return
	}

	if os.Args[1] == "push" && len(os.Args) == 4 {
		if err := u.pushFile(os.Args[2], os.Args[3]); err != nil {
			fmt.Fprintf(os.Stderr, "ADB push error: %v\n", err)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "Pushed %s -> %s\n", os.Args[2], os.Args[3])
		return
	}

	cmd := strings.Join(os.Args[1:], " ")
	if err := u.runShell(cmd); err != nil {
		fmt.Fprintf(os.Stderr, "ADB shell error: %v\n", err)
		os.Exit(1)
	}
}
