/*
 * Copyright (c) 2018 Niklas Ekström
 */

#include <exec/types.h>
#include <exec/ports.h>
#include <exec/tasks.h>
#include <exec/nodes.h>
#include <exec/lists.h>
#include <exec/execbase.h>
#include <exec/memory.h>

#include <libraries/dos.h>
#include <intuition/intuition.h>
#include <graphics/gfxbase.h>
#include <workbench/startup.h>

#include <hardware/intbits.h>

#include <proto/alib.h>
#include <proto/exec.h>
#include <proto/dos.h>
#include <proto/intuition.h>
#include <proto/graphics.h>

#include <stdio.h>
#include <string.h>
#include <time.h>

#include "../a314device/a314.h"
#include "../a314device/proto_a314.h"

// Use the highest bit in a data message signalling that
// the message is an event and not a frame request
#define EVENT_FLAG               (1 << 7)
#define EVENT_MOUSE_MOVE                0
#define EVENT_MOUSE_BUTTONS             1
#define EVENT_MOUSE_LEFT_DOWN           2
#define EVENT_MOUSE_LEFT_UP             3
#define EVENT_MOUSE_RIGHT_DOWN          4
#define EVENT_MOUSE_RIGHT_UP            5
#define EVENT_MOUSE_MIDDLE_DOWN         6
#define EVENT_MOUSE_MIDDLE_UP           7
#define EVENT_RAWKEY                    8
#define EVENT_VANILLAKEY                9

struct IntuitionBase *IntuitionBase = NULL;
struct GfxBase *GfxBase = NULL;

struct Library *A314Base = NULL;

UBYTE *bpl_ptr1;
UBYTE *bpl_ptr2;

int curr_bpl = 0;

struct Screen *screen = NULL;

ULONG socket;

struct A314_IORequest *cmsg;
struct A314_IORequest *rmsg;
UBYTE arbuf[256];
struct A314_IORequest *wmsg;
UBYTE awbuf[256];

BOOL pending_a314_read = FALSE;
BOOL pending_a314_write = FALSE;
BOOL pending_a314_reset = FALSE;

BOOL waiting_for_frame_response = FALSE;
BOOL close_after_next_frame_response = FALSE;
BOOL no_more_frames = FALSE;

BOOL stream_closed = FALSE;

ULONG vblank_counter = 0;
ULONG req_next_frame_at = 0;

struct VBlankData
{
	struct Task *task;
	ULONG signal;
};

static struct VBlankData vblank_data;
extern void VBlankServer();
static struct Interrupt vblank_interrupt;

static struct MsgPort *mp;

void start_a314_cmd(struct A314_IORequest *msg, UWORD command, char *buffer, int length)
{
	msg->a314_Request.io_Command = command;
	msg->a314_Request.io_Error = 0;

	msg->a314_Socket = socket;
	msg->a314_Buffer = buffer;
	msg->a314_Length = length;

	SendIO((struct IORequest *)msg);
}

LONG a314_connect(char *name)
{
	socket = time(NULL);
	start_a314_cmd(cmsg, A314_CONNECT, name, strlen(name));
	return WaitIO((struct IORequest *)cmsg);
}

void start_a314_read()
{
	start_a314_cmd(rmsg, A314_READ, arbuf, 255);
	pending_a314_read = TRUE;
}

void start_a314_write(int length)
{
	start_a314_cmd(wmsg, A314_WRITE, awbuf, length);
	pending_a314_write = TRUE;
}

static void wait_a314_write_complete()
{
	if (pending_a314_write)
	{
		WaitIO((struct IORequest *)wmsg);
		pending_a314_write = FALSE;
	}
}

LONG sync_a314_write(int length)
{
	start_a314_write(length);
	pending_a314_write = FALSE;
	return WaitIO((struct IORequest *)wmsg);
}

void start_a314_reset()
{
	start_a314_cmd(cmsg, A314_RESET, NULL, 0);
	pending_a314_reset = TRUE;
}

LONG sync_a314_reset()
{
	start_a314_reset();
	pending_a314_reset = FALSE;
	return WaitIO((struct IORequest *)cmsg);
}



void handle_a314_read_completed()
{
	pending_a314_read = FALSE;

	if (stream_closed)
		return;

	int res = rmsg->a314_Request.io_Error;
	if (res == A314_READ_OK)
	{
		waiting_for_frame_response = FALSE;

		if (close_after_next_frame_response)
		{
			start_a314_reset();
			stream_closed = TRUE;
			return;
		}

		if (*((UWORD *)&arbuf[0]) == 0)
		{
			printf("No more frames, ending now.\n");
			no_more_frames = TRUE;
			return;
		}

		UBYTE *bpl_ptr;
		if (curr_bpl == 0)
			bpl_ptr = bpl_ptr1;
		else
			bpl_ptr = bpl_ptr2;

		// Set pointers to bitplanes
		screen->BitMap.Planes[0] = &bpl_ptr[10240*0];
		screen->BitMap.Planes[1] = &bpl_ptr[10240*1];
		screen->BitMap.Planes[2] = &bpl_ptr[10240*2];
		screen->BitMap.Planes[3] = &bpl_ptr[10240*3];
		screen->BitMap.Planes[4] = &bpl_ptr[10240*4];

		// Copy the palette
		memcpy(screen->ViewPort.ColorMap->ColorTable, &arbuf[2], 32*2);

		MakeScreen(screen);
		RethinkDisplay();

		start_a314_read();
	}
	else if (res == A314_READ_RESET)
	{
		stream_closed = TRUE;
	}
}

void handle_a314_write_completed()
{
	pending_a314_write = FALSE;

	if (stream_closed)
		return;

	int res = wmsg->a314_Request.io_Error;
	if (res == A314_WRITE_RESET)
	{
		stream_closed = TRUE;
	}
}

void handle_a314_reset_completed()
{
	pending_a314_reset = FALSE;
}

// On vblank, check if it is time to send a request for the next frame
void handle_vblank_signal()
{
	if (req_next_frame_at <= vblank_counter && !waiting_for_frame_response && !no_more_frames)
	{
		// Send a number saying which buffer should be updated
		curr_bpl = (curr_bpl + 1) & 1;

		*((UBYTE *)&awbuf[0]) = (UBYTE)curr_bpl;
		start_a314_write(1);

		waiting_for_frame_response = TRUE;
		req_next_frame_at += 2;     // Request frame every other vblank => 25 fps (PAL)
	}
	vblank_counter += 1;
}

static void handle_intui_message(struct IntuiMessage *im)
{
	printf("Got message\n");
	ULONG class = im->Class;
	ReplyMsg((struct Message *)im);

	switch (class)
	{
		case MOUSEBUTTONS:
			awbuf[0] = EVENT_FLAG;
			awbuf[1] = EVENT_MOUSE_BUTTONS;
			*(WORD *)&awbuf[2] = im->MouseX;
			*(WORD *)&awbuf[4] = im->MouseY;
			switch (im->Code)
			{
				case SELECTDOWN: awbuf[6] = EVENT_MOUSE_LEFT_DOWN;   break;
				case SELECTUP:   awbuf[6] = EVENT_MOUSE_LEFT_UP;     break;
				case MENUDOWN:   awbuf[6] = EVENT_MOUSE_RIGHT_DOWN;  break;
				case MENUUP:     awbuf[6] = EVENT_MOUSE_RIGHT_UP;    break;
// 				case MIDDLEDOWN: awbuf[6] = EVENT_MOUSE_MIDDLE_DOWN; break;
// 				case MIDDLEUP:   awbuf[6] = EVENT_MOUSE_MIDDLE_UP;   break;
			}
			start_a314_write(7);
			break;
		case MOUSEMOVE:
			awbuf[0] = EVENT_FLAG;
			awbuf[1] = EVENT_MOUSE_MOVE;
			*(WORD *)&awbuf[2] = im->MouseX;
			*(WORD *)&awbuf[4] = im->MouseY;
			start_a314_write(6);
			break;
		case RAWKEY:
			awbuf[0] = EVENT_FLAG;
			awbuf[1] = EVENT_RAWKEY;
			*(UWORD *)&awbuf[2] = im->Code;
			*(UWORD *)&awbuf[4] = im->Qualifier;
			start_a314_write(6);
			break;
		case VANILLAKEY:
			// Check for RAmiga-Q
			if (im->Code == 'q' && im->Qualifier == 0x8080)
			{
				close_after_next_frame_response = TRUE;

				if (!waiting_for_frame_response)
				{
					start_a314_reset();
					stream_closed = TRUE;
				}
				break;
			}
			awbuf[0] = EVENT_FLAG;
			awbuf[1] = EVENT_VANILLAKEY;
			*(UWORD *)&awbuf[2] = im->Code;
			*(UWORD *)&awbuf[4] = im->Qualifier;
			start_a314_write(6);
			break;
		default:
			break;
	}
}

int main(int argc, char **argv)
{
	BPTR fh;
	int c;

    struct WBStartup *argmsg;
    struct WBArg *wb_arg;
    BPTR olddir;

    if (argc == 0)
    {
		/* In AmigaOS, argv is a pointer to the WBStartup message
		** when argc is zero.  (run under the Workbench.)
		*/
		argmsg = (struct WBStartup *)argv ;
		wb_arg = argmsg->sm_ArgList;
		wb_arg++;

		if (0 != wb_arg->wa_Lock)
		{
			/* locks supported, change to the proper directory */
			olddir = CurrentDir(wb_arg->wa_Lock) ;

			/* process the file.
			** If you have done the CurrentDir() above, then you can
			** access the file by its name.  Otherwise, you have to
			** examine the lock to get a complete path to the file.
			*/
			fh = Open(wb_arg->wa_Name, MODE_OLDFILE);
			if (!fh)
			{
				goto fail_out0;
			}
			/* change back to the original directory when done.
			** be sure to change back before you exit.
			*/
			CurrentDir(olddir);
		}
		else
		{
			/* something that does not support locks */
			goto fail_out0;
		}
	}
	else if (argc == 2)
	{
		fh = Open(argv[1], MODE_OLDFILE);
		if (!fh)
		{
			printf("Unable to open file %s\n", argv[1]);
			goto fail_out0;
		}
	}
	else
	{
		printf("Use from Workbench as default tool instead\n");
		goto fail_out0;
	}

	IntuitionBase = (struct IntuitionBase *)OpenLibrary("intuition.library", 0);
	GfxBase = (struct GfxBase *)OpenLibrary("graphics.library", 0);

	mp = CreatePort(NULL, 0);

	cmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));

	if (OpenDevice(A314_NAME, 0, (struct IORequest *)cmsg, 0) != 0)
	{
		printf("Unable to open a314.device\n");
		goto fail_out1;
	}

	A314Base = &(cmsg->a314_Request.io_Device->dd_Library);

	wmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));
	rmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));
	memcpy(wmsg, cmsg, sizeof(struct A314_IORequest));
	memcpy(rmsg, cmsg, sizeof(struct A314_IORequest));

	if (a314_connect("xanacs") != A314_CONNECT_OK)
	{
		printf("Unable to connect to xanacs\n");
		goto fail_out2;
	}

	// Allocate memory for dual screen buffers
	bpl_ptr1 = AllocMem(10240*5, MEMF_A314 | MEMF_CHIP);
	bpl_ptr2 = AllocMem(10240*5, MEMF_A314 | MEMF_CHIP);
	if (bpl_ptr1 == NULL || bpl_ptr2 == NULL)
	{
		printf("Unable to allocate A314 chip memory\n");
		sync_a314_reset();
		goto fail_out3;
	}

	// Pack and send screen buffer addresses
	*((ULONG *)&awbuf[0]) = TranslateAddressA314(bpl_ptr1);
	*((ULONG *)&awbuf[4]) = TranslateAddressA314(bpl_ptr2);
	sync_a314_write(8);

	// Send the script/executeable as opened at the start of main(), 223 bytes at a time.
	// First byte is the number of executeable data bytes in the current packet.
	// Transfer ends with the a packet only containing a single 0.
	while (c = Read(fh, awbuf+1, 223))
	{
		printf("Read %d bytes\n", c);
		awbuf[0] = c & 0xff;
		sync_a314_write(c+1);
	}
	Close(fh);
	printf("Done reading file\n");
	awbuf[0] = 0;
	sync_a314_write(1);
	printf("Sent final 0-block\n");

	// Setup and open screen
	struct BitMap bmp =
	{
		40, 256, 0, 5, 0,
		{NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL}
	};

	bmp.Planes[0] = &bpl_ptr1[10240*0];
	bmp.Planes[1] = &bpl_ptr1[10240*1];
	bmp.Planes[2] = &bpl_ptr1[10240*2];
	bmp.Planes[3] = &bpl_ptr1[10240*3];
	bmp.Planes[4] = &bpl_ptr1[10240*4];

	struct NewScreen new_screen =
	{
		0, 0,
		320, 256, 5,
		0, 1,
		0, CUSTOMSCREEN | CUSTOMBITMAP | SCREENQUIET,
		NULL, "Xanacs", NULL, &bmp
	};

	screen = OpenScreen(&new_screen);
	if (screen == NULL)
	{
		printf("Unable to create screen\n");
		sync_a314_reset();
		goto fail_out3;
	}

	// Open window
	struct NewWindow nw =
	{
		0, 0,
		320, 256,
		0, 1,
		MOUSEBUTTONS | MOUSEMOVE | VANILLAKEY | RAWKEY, // IDCMPFlags
		ACTIVATE | SIMPLE_REFRESH | RMBTRAP | REPORTMOUSE | BORDERLESS | BACKDROP, // Flags
		NULL, NULL,
		"xanacs input window",
		screen, NULL,
		0, 0,
		0, 0,
		CUSTOMSCREEN
	};
	struct Window *w = OpenWindow(&nw);
	w->UserPort = mp;

	start_a314_read();

	BYTE vblank_sigbit = AllocSignal(-1);

	ULONG vblanksig = 1 << vblank_sigbit;
	ULONG portsig = 1 << mp->mp_SigBit;

	vblank_data.task = FindTask(NULL);
	vblank_data.signal = vblanksig;

	vblank_interrupt.is_Node.ln_Type = NT_INTERRUPT;
	vblank_interrupt.is_Node.ln_Pri = -60;
	vblank_interrupt.is_Node.ln_Name = "xanacs-vblank-interrupt";
	vblank_interrupt.is_Data = (APTR)&vblank_data;
	vblank_interrupt.is_Code = VBlankServer;

	AddIntServer(INTB_VERTB, &vblank_interrupt);

	while (TRUE)
	{
		ULONG signal = Wait(vblanksig | portsig );
		if (signal & vblanksig)
		{
			handle_vblank_signal();
		}

		if (signal & portsig)
		{
			struct Message *msg;
			while (msg = GetMsg(mp))
			{
				if (msg == (struct Message *)rmsg)
					handle_a314_read_completed();
				else if (msg == (struct Message *)wmsg && wmsg->a314_Request.io_Command == A314_WRITE)
					handle_a314_write_completed();
				else if (msg == (struct Message *)cmsg && cmsg->a314_Request.io_Command == A314_RESET)
					handle_a314_reset_completed();
				else
					handle_intui_message((struct IntuiMessage *)msg);
			}
		}

		if (stream_closed && !pending_a314_read && !pending_a314_write && !pending_a314_reset)
			break;
	}

	RemIntServer(INTB_VERTB, &vblank_interrupt);
	FreeSignal(vblank_sigbit);
	w->UserPort = NULL;
	CloseWindow(w);
	CloseScreen(screen);

fail_out3:
	if (bpl_ptr2)
		FreeMem(bpl_ptr2, 10240*5);
	if (bpl_ptr1)
		FreeMem(bpl_ptr1, 10240*5);

fail_out2:
	CloseDevice((struct IORequest *)cmsg);
	DeleteExtIO((struct IORequest *)rmsg);
	DeleteExtIO((struct IORequest *)wmsg);
fail_out1:
	DeleteExtIO((struct IORequest *)cmsg);
	DeletePort(mp);
	CloseLibrary((struct Library *)GfxBase);
	CloseLibrary((struct Library *)IntuitionBase);
fail_out0:
	return 0;
}
