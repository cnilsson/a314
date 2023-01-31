#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Christian Nilsson

import glob
import os
import select
import struct
import socket
import sys
import time
import subprocess
import shlex
import tempfile

from framegrabber import FrameGrabber

MSG_REGISTER_REQ        = 1
MSG_REGISTER_RES        = 2
MSG_DEREGISTER_REQ      = 3
MSG_DEREGISTER_RES      = 4
MSG_READ_MEM_REQ        = 5
MSG_READ_MEM_RES        = 6
MSG_WRITE_MEM_REQ       = 7
MSG_WRITE_MEM_RES       = 8
MSG_CONNECT             = 9
MSG_CONNECT_RESPONSE    = 10
MSG_DATA                = 11
MSG_EOS                 = 12
MSG_RESET               = 13

# Use the highest bit in a data message signalling that
# the message is an event and not a frame request
EVENT_FLAG              = (1 << 7)
EVENT_MOUSE_MOVE        =        0
EVENT_MOUSE_BUTTONS     =        1
EVENT_MOUSE_LEFT_DOWN   =        2
EVENT_MOUSE_LEFT_UP     =        3
EVENT_MOUSE_RIGHT_DOWN  =        4
EVENT_MOUSE_RIGHT_UP    =        5
EVENT_MOUSE_MIDDLE_DOWN =        6
EVENT_MOUSE_MIDDLE_UP   =        7
EVENT_RAWKEY            =        8
EVENT_VANILLAKEY        =        9

def wait_for_msg():
    header = b''
    while len(header) < 9:
        data = drv.recv(9 - len(header))
        header += data
    (plen, pstream, ptype) = struct.unpack('=IIB', header)
    payload = b''
    while len(payload) < plen:
        data = drv.recv(plen - len(payload))
        payload += data
    return (header, payload)

def send_register(name):
    m = struct.pack('=IIB', len(name), 0, MSG_REGISTER_REQ) + name
    drv.sendall(m)

def send_write_mem_req(address, data):
    m = struct.pack('=IIBI', 4 + len(data), 0, MSG_WRITE_MEM_REQ, address) + data
    drv.sendall(m)

def send_connect_response(stream_id, result):
    m = struct.pack('=IIBB', 1, stream_id, MSG_CONNECT_RESPONSE, result)
    drv.sendall(m)

def send_data(stream_id, data):
    m = struct.pack('=IIB', len(data), stream_id, MSG_DATA) + data
    drv.sendall(m)

def send_eos(stream_id):
    m = struct.pack('=IIB', 0, stream_id, MSG_EOS)
    drv.sendall(m)

def send_reset(stream_id):
    m = struct.pack('=IIB', 0, stream_id, MSG_RESET)
    drv.sendall(m)

write_mem_q = []
current_write_mem_stream_id = 0

def enqueue_write_mem_req(stream_id, address, data):
    global current_write_mem_stream_id

    if current_write_mem_stream_id == 0:
        current_write_mem_stream_id = stream_id
        send_write_mem_req(address, data)
    else:
        write_mem_q.append((stream_id, address, data))
    
sessions = {}

class VideoPlayerSession(object):
    def __init__(self, stream_id):
        self.stream_id = stream_id

        self.reset_after = None
        self.received_bpl_ptrs = False
        self.received_cmd = False
        self.linux_process = None
        self.cmdbuffer = bytearray()

        self.grabber = FrameGrabber()

    def start(self):
        self.fc = 0
        self.read_next_frame()

    def close(self):
        if self.linux_process:
            print('Kill process...')
            self.linux_process.terminate()
            try:
                self.linux_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                print('Process didn\'t stop from SIGTERM, sending SIGKILL')
                self.linux_process.kill()
                self.linux_process.communicate()
        print('process killed')
        self.grabber.close()
        del sessions[self.stream_id]

    def read_next_frame(self):
        self.pal, self.bpl_data = self.grabber.get_planar_frame(self.fc)
        self.fc = self.fc + 1

    def process_msg_data(self, data):
        if not self.received_bpl_ptrs:
            # Startup begins with addresses for the two chip mem areas used for the Amiga screen
            self.addresses = struct.unpack('>II', data)
            self.received_bpl_ptrs = True
        elif not self.received_cmd:
            # After that, the Linux application/script/whatever is transferred
            if data[0] > 0:
                print('Received {:d} sized packet with {:d} bytes of command data'.format(len(data), data[0]))
                self.cmdbuffer.extend(data[1:data[0]+1])
            else:
                print('All data received, total: {:d} bytes'.format(len(self.cmdbuffer)))
                tmpfile = '/tmp/' + next(tempfile._get_candidate_names())
                with open(tmpfile, 'wb') as f:
                    f.write(self.cmdbuffer)
                os.chmod(tmpfile, 0o700)
                self.received_cmd = True
                display_num = self.grabber.get_display_num()
                shellcmd = tmpfile + f' DISPLAY={display_num}'
                print(f'shellcmd: {shellcmd}')
                self.linux_process = subprocess.Popen(shlex.split(shellcmd))
        else:
            if data[0] & EVENT_FLAG:
                # Message contains an input event
                self.process_input_event(data[1], data[2:])
            else:
                # All other messages are requests for a new frame
                self.next_bpl = data[0]
                if self.bpl_data is None:
                    send_data(self.stream_id, struct.pack('>H', 0))
                else:
                    address = self.addresses[self.next_bpl]
                    enqueue_write_mem_req(self.stream_id, address, self.bpl_data)

    def process_write_mem_res(self, data):
        send_data(self.stream_id, struct.pack('>H', 1) + self.pal)
        self.read_next_frame()

    def handle_timeout(self):
        if self.reset_after and self.reset_after < time.time():
            send_reset(self.stream_id)
            self.close()

    def process_input_event(self, event, event_data):
        if event == EVENT_MOUSE_MOVE:
            mouseX, mouseY = struct.unpack('>hh', event_data)
            print('Mouse move event: ({:3d} {:3d})'.format(mouseX, mouseY))
            self.grabber.send_mouse(mouseX, mouseY, 0)
        elif event == EVENT_MOUSE_BUTTONS:
            mouseX, mouseY, action = struct.unpack('>hhB', event_data)
            print('Mouse action event: ({:3d} {:3d}   {:d})'.format(mouseX, mouseY, action))
            self.grabber.send_mouse(mouseX, mouseY, action)
        elif event == EVENT_RAWKEY:
            code, qualifier = struct.unpack('>HH', event_data)
            print('Keyboard raw event: (0x{:04x} 0x{:04x})'.format(code, qualifier))
            self.grabber.send_raw_key(code, qualifier)
        elif event == EVENT_VANILLAKEY:
            code, qualifier = struct.unpack('>HH', event_data)
            print('Keyboard vanilla event: (0x{:04x} 0x{:04x})'.format(code, qualifier))
            self.grabber.send_key(code, qualifier)

    def fileno(self):
        return self.fd

def process_drv_write_mem_res(payload):
    global current_write_mem_stream_id

    stream_id = current_write_mem_stream_id

    if len(write_mem_q) != 0:
        current_write_mem_stream_id, address, data = write_mem_q.pop(0)
        send_write_mem_req(address, data)
    else:
        current_write_mem_stream_id = 0

    if stream_id in sessions:
        s = sessions[stream_id]
        s.process_write_mem_res(payload)

def process_drv_msg(stream_id, ptype, payload):
    if ptype == MSG_CONNECT:
        if payload == b'xanacs':
            s = VideoPlayerSession(stream_id)
            sessions[stream_id] = s
            s.start()
            send_connect_response(stream_id, 0)
        else:
            send_connect_response(stream_id, 3)
    elif ptype == MSG_WRITE_MEM_RES:
        process_drv_write_mem_res(payload)
    elif stream_id in sessions:
        s = sessions[stream_id]

        if ptype == MSG_DATA:
            s.process_msg_data(payload)
        elif ptype == MSG_EOS:
            send_eos(s.stream_id)
            s.close()
        elif ptype == MSG_RESET:
            s.close()

done = False

try:
    idx = sys.argv.index('-ondemand')
except ValueError:
    idx = -1

if idx != -1:
    fd = int(sys.argv[idx + 1])
    drv = socket.socket(fileno=fd)
else:
    drv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    drv.connect(('localhost', 7110))
    drv.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    send_register(b'xanacs')
    header, payload = wait_for_msg()
    if payload[0] != 1:
        print('Unable to register xanacs with driver')
        drv.close()
        done = True

rbuf = b''

if not done:
    print('Video player server is running')

while not done:
    sel_fds = [drv]
    if idx == -1:
        sel_fds.append(sys.stdin)
    rfd, wfd, xfd = select.select(sel_fds, [], [], 5.0)

    for fd in rfd:
        if fd == sys.stdin:
            line = sys.stdin.readline()
            if not line or line.startswith('quit'):
                drv.close()
                done = True
        elif fd == drv:
            buf = drv.recv(1024)
            if not buf:
                drv.close()
                done = True
            else:
                rbuf += buf
                while True:
                    if len(rbuf) < 9:
                        break

                    (plen, stream_id, ptype) = struct.unpack('=IIB', rbuf[:9])
                    if len(rbuf) < 9 + plen:
                        break

                    rbuf = rbuf[9:]
                    payload = rbuf[:plen]
                    rbuf = rbuf[plen:]

                    process_drv_msg(stream_id, ptype, payload)

    if not done:
        for s in sessions.values():
            s.handle_timeout()
