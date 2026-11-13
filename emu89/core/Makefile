# Compile le cœur C (Musashi + carte mémoire TI-89) en bibliothèque partagée.
MUSASHI = ../musashi
CC      = gcc
CFLAGS  = -O2 -fPIC -w -I. -I$(MUSASHI) -I$(MUSASHI)/softfloat -DMUSASHI_CNF='"ti89conf.h"'

OBJS = core.o m68kcpu.o m68kops.o m68kdasm.o softfloat.o

libti89core.so: $(OBJS)
	$(CC) -shared -o $@ $(OBJS) -lm

$(MUSASHI)/m68kops.c: $(MUSASHI)/m68k_in.c
	$(MAKE) -C $(MUSASHI) m68kops.c

m68kops.o: $(MUSASHI)/m68kops.c
	$(CC) $(CFLAGS) -c $< -o $@
m68kcpu.o: $(MUSASHI)/m68kcpu.c $(MUSASHI)/m68kops.c
	$(CC) $(CFLAGS) -c $< -o $@
m68kdasm.o: $(MUSASHI)/m68kdasm.c
	$(CC) $(CFLAGS) -c $< -o $@
softfloat.o: $(MUSASHI)/softfloat/softfloat.c
	$(CC) $(CFLAGS) -c $< -o $@
core.o: core.c ti89conf.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f *.o libti89core.so

# ---- Windows : DLL 64 bits compilée depuis Linux/WSL avec MinGW (make windows) ----
MINGW   = x86_64-w64-mingw32-gcc
WINOBJ  = win/core.o win/m68kcpu.o win/m68kops.o win/m68kdasm.o win/softfloat.o

windows: ti89core.dll

ti89core.dll: $(WINOBJ)
	$(MINGW) -shared -static-libgcc -o $@ $(WINOBJ) -Wl,--export-all-symbols

win/%.o: %.c ti89conf.h | win
	$(MINGW) $(CFLAGS) -c $< -o $@
win/m68kops.o: $(MUSASHI)/m68kops.c | win
	$(MINGW) $(CFLAGS) -c $< -o $@
win/m68kcpu.o: $(MUSASHI)/m68kcpu.c $(MUSASHI)/m68kops.c | win
	$(MINGW) $(CFLAGS) -c $< -o $@
win/m68kdasm.o: $(MUSASHI)/m68kdasm.c | win
	$(MINGW) $(CFLAGS) -c $< -o $@
win/softfloat.o: $(MUSASHI)/softfloat/softfloat.c | win
	$(MINGW) $(CFLAGS) -c $< -o $@
win:
	mkdir -p win

clean-windows:
	rm -rf win ti89core.dll
