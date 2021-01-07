/*
 * C2P code copied with a few adjustments from Mikael Kalms' C2P collection
 * https://github.com/Kalmalyzer/kalms-c2p which when acquired 2021-01-12 was
 * categorized as Public Domain by the author.
 *
 * Original header included below.
 */


/*
   Chunky-to-Planar conversion outlined in C
   ... using "bit-matrix transposition"
   techniques (define matrix transposition recursively, then parallelize
   it, create optimized merge operations (bit-exchanging ops), and
   compensate for non-square matrix).
   The conversion code presented herein will, if compiled on a 680x0
   system with a good optimizing compiler, produce almost exactly the
   same conversion code as that used in the 680x0 assembly language
   routines. [Those assembly routines are
   additionally optimized to the limit concerning the memory
   reads/writes.]
   Mikael Kalms, 1999-01-07
*/



#include <sys/types.h>
#include <byteswap.h>

void indexed2planar(u_int8_t *input, u_int8_t *output, unsigned int pixels, unsigned int bitplanes)
{
    u_int32_t	d[8];		// D for Data, nothing to do with
    u_int32_t	t;			// 680x0 d-regs! nonono :)

// The actual merge operation used
#define MERGE(reg1, reg2, temp, shift, mask) \
	temp = reg2; \
	temp >>= shift; \
	temp ^= reg1; \
	temp &= mask; \
	reg1 ^= temp; \
	temp <<= shift; \
	reg2 ^= temp;

    // Convert 32 pixels, 8bpl
    u_int32_t *source = (u_int32_t *)input;
    u_int32_t *dest = (u_int32_t *)output;
    for (int r = 0; r < pixels/8/4; r++)
    {
        // Read in original pixels
        for (int i = 0; i < 8; i++)
            d[i] = bswap_32(*source++);

        // Do the magic
        MERGE(d[0], d[1], t, 4, 0x0f0f0f0f);
        MERGE(d[2], d[3], t, 4, 0x0f0f0f0f);
        MERGE(d[4], d[5], t, 4, 0x0f0f0f0f);
        MERGE(d[6], d[7], t, 4, 0x0f0f0f0f);
        MERGE(d[0], d[4], t, 16, 0x0000ffff);
        MERGE(d[1], d[5], t, 16, 0x0000ffff);
        MERGE(d[2], d[6], t, 16, 0x0000ffff);
        MERGE(d[3], d[7], t, 16, 0x0000ffff);
        MERGE(d[0], d[4], t, 2, 0x33333333);
        MERGE(d[1], d[5], t, 2, 0x33333333);
        MERGE(d[2], d[6], t, 2, 0x33333333);
        MERGE(d[3], d[7], t, 2, 0x33333333);
        MERGE(d[0], d[2], t, 8, 0x00ff00ff);
        MERGE(d[1], d[3], t, 8, 0x00ff00ff);
        MERGE(d[4], d[6], t, 8, 0x00ff00ff);
        MERGE(d[5], d[7], t, 8, 0x00ff00ff);
        MERGE(d[0], d[2], t, 1, 0x55555555);
        MERGE(d[1], d[3], t, 1, 0x55555555);
        MERGE(d[4], d[6], t, 1, 0x55555555);
        MERGE(d[5], d[7], t, 1, 0x55555555);
        // d[01234567] now contains bitplane data
        // for bitplanes 73625140, in that order (sorry 'bout that,
        // but I'm not going to do any tradeoffs just to make the
        // code look better -- you won't be able to fiddle it away
        // for free in the above merging scheme anyway)
        switch(bitplanes)
        {
            case 8:
                dest[(pixels/8/4*7)+r] = bswap_32(d[0]);
            case 7:
                dest[(pixels/8/4*6)+r] = bswap_32(d[2]);
            case 6:
                dest[(pixels/8/4*5)+r] = bswap_32(d[4]);
            case 5:
                dest[(pixels/8/4*4)+r] = bswap_32(d[6]);
            case 4:
                dest[(pixels/8/4*3)+r] = bswap_32(d[1]);
            case 3:
                dest[(pixels/8/4*2)+r] = bswap_32(d[3]);
            case 2:
                dest[(pixels/8/4)+r] = bswap_32(d[5]);
            case 1:
                dest[r] = bswap_32(d[7]);
        }
    }
    return;
}

// Converts truecolor to a grayscale image, at least for now.
void truecolor2planar(u_int8_t *input, u_int8_t *output, unsigned int pixels, unsigned int bitplanes)
{
    u_int8_t indexed[pixels];

    unsigned int i, sum;
    for(i = 0; i < pixels; i++)
    {
        sum = input[i*4] + input[(i*4)+1] + input[(i*4)+2];
        indexed[i] = (sum / 3) >> 4;
    }

    indexed2planar((u_int8_t *)&indexed, output, pixels, bitplanes);
}
