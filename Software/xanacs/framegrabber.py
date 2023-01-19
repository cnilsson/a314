#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Christian Nilsson

from multiprocessing import Process, Pipe, shared_memory

from PIL import Image, ImageOps
import imagequant
from pyvirtualdisplay import display as virtdisplay
from Xlib import display, X

from ctypes import c_char, c_char_p, CDLL

lib_path = '/opt/a314/libcc2p.so'
try:
    cc2p_lib = CDLL(lib_path)
except Exception as e:
    print('Failed to load C chunky 2 planar: {}'.format(e))

DEBUG = False
use_libimagequant = False

class FrameGrabber(object):
    def __init__(self):
        self._w = 320
        self._h = 256

        self._display = virtdisplay.Display(size=(320, 256))
        self._display.start()
        self._x11_display_num = self._display.new_display_var
        if DEBUG: print(f'X11 Display number: {self._x11_display_num}')

        self._num_graboids = 4
        self._graboids = []
        for g in range(0, self._num_graboids):
            shm_a = shared_memory.SharedMemory(create=True, size=64+self._w*self._h*5//8)
            parent_conn, child_conn = Pipe()
            graboid = Process(target=self.framegrabber_process, args=(child_conn, shm_a.name, g, self._x11_display_num))
            graboid.start()
            self._graboids.append((parent_conn, shm_a, graboid))

    def framegrabber_process(self, conn, shm_name, g, display_name):
        if DEBUG: print(f'Graboid {g} started!')
        root = display.Display(display_name).screen().root
        shm_output = shared_memory.SharedMemory(shm_name)
        frame_num = conn.recv()
        while frame_num != None:
            if DEBUG: print(f'Graboid {g} start #{frame_num}')
            image_data = root.get_image(0, 0, self._w, self._h, X.ZPixmap, 0xffffffff)
            if use_libimagequant == True:
                # This looks sooo much better, but is equally slower...
                quantized_image, quantized_palette = imagequant.quantize_raw_rgba_bytes(image_data.data, self._w, self._h, dithering_level=1.0, max_colors=32)

                amiga_palette = bytearray(64)
                for c in range(0, 32):
                    amiga_palette[2*c] = quantized_palette[4*c+2] >> 4
                    amiga_palette[2*c+1] = (quantized_palette[4*c+1] & 0xf0) | (quantized_palette[4*c] >> 4)
            else:
                original_image = Image.frombuffer("RGB", (self._w, self._h), image_data.data, "raw", "BGRX")

                # Keep top 4 bits of colour values. This is not really needed, but it seems
                # to lighten the CPU load enough for 25 fps playback on an RPi Zero 2
                posterized_image = ImageOps.posterize(image=original_image, bits=4)

                # Quantize image, reducing to 32 colours
                temp_image = posterized_image.quantize(colors=32, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)
                quantized_palette = temp_image.getpalette('RGB')
                quantized_image = temp_image.tobytes()

                amiga_palette = bytearray(64)
                for c in range(0, 32):
                    amiga_palette[2*c] = quantized_palette[3*c] >> 4
                    amiga_palette[2*c+1] = (quantized_palette[3*c+1] & 0xf0) | (quantized_palette[3*c+2] >> 4)

            if DEBUG: print(f'Graboid {g} sending #{frame_num}')

            # Perform chunky-to-planar conversion and store in shared mem area
            shm_output.buf[:64] = amiga_palette
            shm_output.buf[64:] = bytes(self.c2p(quantized_image, self._w, self._h, 5))
            conn.send(frame_num)

            if DEBUG: print(f'Graboid {g} sent #{frame_num}')
            frame_num = conn.recv()

    @staticmethod
    def c2p(raw, width, height, depth):
        """Call C function to perform chunky to planar conversion"""
        indexed2planar = cc2p_lib.indexed2planar
        indexed2planar.restype = None

        c_arr_in = (c_char_p)(raw)
        c_arr_out = (c_char * (width*height*depth//8))()

        indexed2planar(c_arr_in, c_arr_out, width*height, depth)
        return c_arr_out

    def get_planar_frame(self, frame_number):
        if frame_number < self._num_graboids:
            if DEBUG: print(f'Faking #{frame_number}')
            amiga_palette = bytes(64)
            amiga_image = bytes(self._w*self._h*5//8)
        else:
            if DEBUG: print(f'Getting #{frame_number} from {frame_number%self._num_graboids}')
            self._graboids[frame_number%self._num_graboids][0].recv()
            amiga_palette = self._graboids[frame_number%self._num_graboids][1].buf[:64]
            amiga_image   = self._graboids[frame_number%self._num_graboids][1].buf[64:]

        if DEBUG: print(f'Requesting #{frame_number} from {frame_number%self._num_graboids}')
        self._graboids[frame_number % self._num_graboids][0].send(frame_number)

        return amiga_palette, amiga_image

    def get_display_num(self):
        return self._x11_display_num
