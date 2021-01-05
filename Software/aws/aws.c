/*
 * Copyright (c) 2021 Niklas Ekström
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
#include <graphics/gfx.h>

#include <proto/exec.h>
#include <proto/intuition.h>
#include <proto/graphics.h>

#include <stdio.h>
#include <string.h>
#include <time.h>

#include "../a314device/a314.h"
#include "../a314device/proto_a314.h"

#define AWS_REQ_OPEN_WINDOW 1
#define AWS_REQ_CLOSE_WINDOW 2
#define AWS_REQ_FLIP_BUFFER 3
#define AWS_RES_OPEN_WINDOW_FAIL 4
#define AWS_RES_OPEN_WINDOW_SUCCESS 5
#define AWS_EVENT_CLOSE_WINDOW 6

struct WindowInfo
{
	struct WindowInfo *next;
	struct WindowInfo *prev;
	struct Window *window;
	struct BitMap bm;
	UBYTE *buffer;
	UWORD buf_width;
	UWORD buf_height;
	UBYTE buf_depth;
	UBYTE wid;
	char title[128];
};

struct WindowInfo *windows_head = NULL;
struct WindowInfo *windows_tail = NULL;

struct MsgPort *mp;
struct MsgPort *wmp;

ULONG socket;

struct Library *A314Base;
struct IntuitionBase *IntuitionBase;
struct GfxBase *GfxBase;

struct A314_IORequest *cmsg;
struct A314_IORequest *rmsg;
struct A314_IORequest *wmsg;

UBYTE arbuf[256];
UBYTE awbuf[256];

BOOL pending_a314_read = FALSE;
BOOL pending_a314_write = FALSE;
BOOL pending_a314_reset = FALSE;

BOOL stream_closed = FALSE;

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

void wait_a314_write_complete()
{
	if (pending_a314_write)
	{
		WaitIO((struct IORequest *)wmsg);
		pending_a314_write = FALSE;
	}
}

void start_a314_write(int length)
{
	start_a314_cmd(wmsg, A314_WRITE, awbuf, length);
	pending_a314_write = TRUE;
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

struct WindowInfo *find_window_by_id(ULONG wid)
{
	struct WindowInfo *wi = windows_head;
	while (wi)
	{
		if (wi->wid == wid)
			return wi;
		wi = wi->next;
	}
	return wi;
}

struct WindowInfo *find_window(struct Window *w)
{
	struct WindowInfo *wi = windows_head;
	while (wi)
	{
		if (wi->window == w)
			return wi;
		wi = wi->next;
	}
	return wi;
}

void append_window(struct WindowInfo *wi)
{
	wi->next = NULL;
	wi->prev = windows_tail;
	if (windows_tail)
		windows_tail->next = wi;
	else
		windows_head = wi;
	windows_tail = wi;
}

void remove_window(struct WindowInfo *wi)
{
	if (wi->prev)
		wi->prev->next = wi->next;
	else
		windows_head = wi->next;

	if (wi->next)
		wi->next->prev = wi->prev;
	else
		windows_tail = wi->prev;

	wi->prev = NULL;
	wi->next = NULL;
}

void handle_req_open_window()
{
	struct WindowInfo *wi = (struct WindowInfo *)AllocMem(sizeof(struct WindowInfo), MEMF_CLEAR);

	UBYTE wid = arbuf[1];
	UWORD left = *(UWORD *)&arbuf[2];
	UWORD top = *(UWORD *)&arbuf[4];
	UWORD width = *(UWORD *)&arbuf[6];
	UWORD height = *(UWORD *)&arbuf[8];
	memcpy(wi->title, &arbuf[10], rmsg->a314_Length - 10);

	struct NewWindow nw =
	{
		left, top,
		width, height,
		0, 1,
		0,
		WINDOWCLOSE | ACTIVATE | WINDOWDEPTH | WINDOWDRAG | SIMPLE_REFRESH,
		NULL, NULL,
		wi->title,
		NULL, NULL,
		0, 0,
		0, 0,
		WBENCHSCREEN
	};

	struct Window *w = OpenWindow(&nw);
	if (w)
	{
		w->UserPort = mp;
		ModifyIDCMP(w, CLOSEWINDOW | REFRESHWINDOW);

		UWORD bw = w->Width - (w->BorderLeft + w->BorderRight);
		UWORD bh = w->Height - (w->BorderTop + w->BorderBottom);
		UWORD bd = w->WScreen->BitMap.Depth;

		ULONG bpr = ((bw + 15) & ~15) >> 3;
		void *buffer = AllocMem(bpr * bh * bd, MEMF_A314 | MEMF_CHIP);
		if (!buffer)
			CloseWindow(w);
		else
		{
			wi->window = w;
			wi->buffer = buffer;
			wi->buf_width = bw;
			wi->buf_height = bh;
			wi->buf_depth = bd;
			wi->wid = wid;

			wi->bm.BytesPerRow = bpr;
			wi->bm.Rows = bh;
			wi->bm.Depth = bd;
			for (int i = 0; i < bd; i++)
				wi->bm.Planes[i] = wi->buffer + bpr * bh * i;

			append_window(wi);

			wait_a314_write_complete();

			awbuf[0] = AWS_RES_OPEN_WINDOW_SUCCESS;
			awbuf[1] = wid;
			*(ULONG *)&awbuf[2] = TranslateAddressA314(buffer);
			*(UWORD *)&awbuf[6] = bw;
			*(UWORD *)&awbuf[8] = bh;
			*(UWORD *)&awbuf[10] = bd;
			start_a314_write(12);
			return;
		}
	}

	FreeMem(wi, sizeof(struct WindowInfo));

	wait_a314_write_complete();

	awbuf[0] = AWS_RES_OPEN_WINDOW_FAIL;
	awbuf[1] = wid;
	start_a314_write(2);
}

void handle_req_close_window()
{
	UBYTE wid = arbuf[1];
	struct WindowInfo *wi = find_window_by_id(wid);
	if (!wi)
		return;

	remove_window(wi);

	ULONG pixels = wi->buf_width;
	pixels = (pixels + 15) & ~15;
	pixels = pixels * wi->buf_height * wi->buf_depth;
	FreeMem(wi->buffer, pixels >> 3);

	wi->window->UserPort = NULL;
	CloseWindow(wi->window);

	FreeMem(wi, sizeof(struct WindowInfo));
}

void redraw_window(struct WindowInfo *wi)
{
	struct RastPort rp;
	rp.Layer = NULL;
	rp.BitMap = &wi->bm;
	struct Window *w = wi->window;
	ClipBlit(&rp, 0, 0, w->RPort, w->BorderLeft, w->BorderTop, wi->buf_width, wi->buf_height, 0xc0);
}

void handle_req_flip_buffer()
{
	UBYTE wid = arbuf[1];
	struct WindowInfo *wi = find_window_by_id(wid);
	if (wi)
		redraw_window(wi);
}

void handle_intui_message(struct IntuiMessage *im)
{
	ULONG class = im->Class;
	struct WindowInfo *wi = find_window(im->IDCMPWindow);
	ReplyMsg((struct Message *)im);

	switch (class)
	{
		case CLOSEWINDOW:
			wait_a314_write_complete();
			awbuf[0] = AWS_EVENT_CLOSE_WINDOW;
			awbuf[1] = wi->wid;
			start_a314_write(2);
			break;

		case REFRESHWINDOW:
			BeginRefresh(wi->window);
			redraw_window(wi);
			EndRefresh(wi->window, TRUE);
			break;
	}
}

void handle_a314_read_completed()
{
	pending_a314_read = FALSE;

	if (stream_closed)
		return;

	int res = rmsg->a314_Request.io_Error;
	if (res == A314_READ_OK)
	{
		switch (arbuf[0])
		{
			case AWS_REQ_OPEN_WINDOW:
				handle_req_open_window();
				break;
			case AWS_REQ_CLOSE_WINDOW:
				handle_req_close_window();
				break;
			case AWS_REQ_FLIP_BUFFER:
				handle_req_flip_buffer();
				break;
		}

		start_a314_read();
	}
	else if (res == A314_READ_EOS)
	{
		start_a314_reset();
		stream_closed = TRUE;
	}
	else if (res == A314_READ_RESET)
		stream_closed = TRUE;
}

int main()
{
	LONG old_priority = SetTaskPri(FindTask(NULL), 20);

	GfxBase = (struct GfxBase *)OpenLibrary("graphics.library", 0);
	IntuitionBase = (struct IntuitionBase *)OpenLibrary("intuition.library", 0);

	mp = CreatePort(NULL, 0);
	wmp = CreatePort(NULL, 0);
	cmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));

	if (OpenDevice(A314_NAME, 0, (struct IORequest *)cmsg, 0) != 0)
	{
		printf("Unable to open a314.device\n");
		goto fail_out1;
	}

	A314Base = &(cmsg->a314_Request.io_Device->dd_Library);

	rmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));
	wmsg = (struct A314_IORequest *)CreateExtIO(mp, sizeof(struct A314_IORequest));
	memcpy(rmsg, cmsg, sizeof(struct A314_IORequest));
	memcpy(wmsg, cmsg, sizeof(struct A314_IORequest));
	wmsg->a314_Request.io_Message.mn_ReplyPort = wmp;

	if (a314_connect("awsproxy") != A314_CONNECT_OK)
	{
		printf("Unable to connect to awsproxy\n");
		goto fail_out2;
	}

	start_a314_read();

	ULONG mp_sig = 1 << mp->mp_SigBit;
	ULONG wmp_sig = 1 << wmp->mp_SigBit;

	printf("Press ctrl-c to exit...\n");

	while (TRUE)
	{
		ULONG signal = Wait(mp_sig | wmp_sig | SIGBREAKF_CTRL_C);

		if (signal & wmp_sig)
		{
			struct Message *msg = GetMsg(wmp);
			if (msg)
				pending_a314_write = FALSE;
		}

		if (signal & mp_sig)
		{
			struct Message *msg;
			while (msg = GetMsg(mp))
			{
				if (msg == (struct Message *)rmsg)
					handle_a314_read_completed();
				else if (msg == (struct Message *)cmsg)
					pending_a314_reset = FALSE;
				else
					handle_intui_message((struct IntuiMessage *)msg);
			}
		}

		if (signal & SIGBREAKF_CTRL_C)
		{
			start_a314_reset();
			stream_closed = TRUE;
		}

		if (stream_closed && !pending_a314_read && !pending_a314_write && !pending_a314_reset)
			break;
	}

fail_out2:
	DeleteExtIO((struct IORequest *)wmsg);
	DeleteExtIO((struct IORequest *)rmsg);
	CloseDevice((struct IORequest *)cmsg);
fail_out1:
	DeleteExtIO((struct IORequest *)cmsg);
	DeletePort(wmp);
	DeletePort(mp);
	CloseLibrary((struct Library *)IntuitionBase);
	CloseLibrary((struct Library *)GfxBase);
	SetTaskPri(FindTask(NULL), old_priority);
	return 0;
}