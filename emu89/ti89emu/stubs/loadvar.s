| Création d'une variable dans la TI-89 émulée, en appelant les fonctions d'AMS.
| Équivalent C :
|   HSym hs = SymAdd(nom);  HANDLE h = HeapAlloc(taille);
|   DerefSym(hs)->handle = h;  memcpy(HeapDeref(h), donnees, taille);
| Les paramètres (3 mots longs absolus) sont écrits par l'émulateur à « params ».
| Fin : boucle sur « done », d0 = 1 si succès, 0 sinon.

        .text
        .even
start:
        movea.l 0xC8,%a5                | table des appels ROM d'AMS
        move.l  p_name(%pc),-(%sp)      | SymAdd(nom)  (0x5C)
        movea.l (0x5C*4,%a5),%a0
        jsr     (%a0)
        addq.l  #4,%sp
        move.l  %d0,%d3                 | HSym
        beq.s   fail
        move.l  p_size(%pc),-(%sp)      | HeapAlloc(taille)  (0x90)
        movea.l (0x90*4,%a5),%a0
        jsr     (%a0)
        addq.l  #4,%sp
        move.w  %d0,%d4                 | HANDLE
        beq.s   fail
        move.l  %d3,-(%sp)              | DerefSym(hs)  (0x79) -> a0
        movea.l (0x79*4,%a5),%a0
        jsr     (%a0)
        addq.l  #4,%sp
        move.w  %d4,12(%a0)             | sym->handle = h
        move.w  %d4,-(%sp)              | HeapDeref(h)  (0x96) -> a0
        movea.l (0x96*4,%a5),%a0
        jsr     (%a0)
        addq.l  #2,%sp
        movea.l p_data(%pc),%a1
        move.l  p_size(%pc),%d1
copy:   move.b  (%a1)+,(%a0)+
        subq.l  #1,%d1
        bne.s   copy
        moveq   #1,%d0
        bra.s   done
fail:   moveq   #0,%d0
done:   bra.s   done
        .even
params:
p_size: .long   0                       | taille des données (mot de longueur compris)
p_name: .long   0                       | adresse du SYM_STR (\0nom\0, pointe sur le \0 final)
p_data: .long   0                       | adresse des données
