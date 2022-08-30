#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Christian Nilsson

from Xlib import display, X
from PIL import Image, ImageOps

from ctypes import c_char, c_char_p, CDLL

lib_path = './libcc2p.so'
try:
    cc2p_lib = CDLL(lib_path)
except Exception as e:
    print('Failed to load C chunky 2 planar: {}'.format(e))

def c2p(raw, width, height, depth):
    """Call C function to perform chunky to planar conversion"""
    indexed2planar = cc2p_lib.indexed2planar
    indexed2planar.restype = None

    c_arr_in = (c_char_p)(raw)
    c_arr_out = (c_char * (width*height*depth//8))()

    indexed2planar(c_arr_in, c_arr_out, width*height, depth)
    return c_arr_out[:]

class FrameGrabber(object):
    def __init__(self):
        self.w = 320
        self.h = 256

        self.d = display.Display(':0')
        self.root = self.d.screen().root

    def get_planar_frame(self):
        raw = self.root.get_image(0, 0, self.w, self.h, X.ZPixmap, 0xffffffff)
        fullimg = Image.frombytes("RGB", (self.w, self.h), raw.data, "raw", "BGRX")

        # Keep top 4 bits of colour values
        posterized_image = ImageOps.posterize(fullimg, 4)

        # Quantize image, reducing to 16 colours
        quantized_image = posterized_image.quantize(method=Image.Quantize.MAXCOVERAGE, colors=16)
        quantized_palette = quantized_image.getpalette('RGB')

        # Perform chunky-to-planar conversion
        amiga_image = c2p(quantized_image.tobytes(), self.w, self.h, 4)

        amiga_palette = bytearray(32)


        for c in range(0, 16):
            amiga_palette[2*c] = quantized_palette[3*c] >> 4
            amiga_palette[2*c+1] = (quantized_palette[3*c+1] & 0xf0) | (quantized_palette[3*c+2] >> 4)

        return amiga_palette, amiga_image
