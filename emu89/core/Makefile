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
