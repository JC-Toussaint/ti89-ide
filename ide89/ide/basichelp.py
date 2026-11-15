"""Online help of Basic89: syntax, description and example of each keyword (F1 in the
editor, and the syntax in the status bar when the cursor is on a keyword)."""

# name -> (syntax, description, example)
HELP = {
    # ------------------------------------------------------------ declarations
    "DIM": ("DIM name [(bounds)] AS type [= value] [, ...]",
            "Declares variables. Every variable must be declared. Outside a SUB/FUNCTION the "
            "variable is global. An array goes from 0 to its bound; several bounds make a "
            "multi-dimension array. DIM sets the variable to 0 (or \"\") unless a value is given.",
            "DIM score AS INTEGER, speed AS FIXED = 1.5\nDIM grid(20, 12) AS INTEGER\nDIM name AS STRING * 8"),
    "CONST": ("CONST NAME = value [, NAME2 = value]",
              "Defines constants (integer, FIXED or text), replaced by their value when compiling. "
              "Integer constants can be used as array bounds.",
              "CONST ROWS = 15, COLS = 30\nCONST TITLE = \"Maze\""),
    "TYPE": ("TYPE Name\n  field [(bounds)] AS type\n  ...\nEND TYPE",
             "Defines a record: a group of fields. Fields can be arrays or other TYPEs. A TYPE "
             "variable is copied with =. Passed to a SUB, it is read only (not copied); BYREF lets "
             "the SUB change it, BYVAL gives a copy.",
             "TYPE Enemy\n  x AS INTEGER\n  y AS FIXED\n  alive AS BOOLEAN\nEND TYPE\nDIM e(10) AS Enemy\ne(3).x = 40"),
    "SUB": ("SUB name [([BYVAL | BYREF] param [()] AS type, ...)]\n  ...\nEND SUB",
            "Defines a procedure. Call it with its name and its arguments (or CALL name(...)). "
            "Without keyword, the SUB cannot change the caller's variable: numbers are copied, "
            "STRINGs and TYPEs are read only. BYREF: the SUB changes the caller's variable; "
            "BYVAL: a copy (BYVAL t AS STRING * 20 keeps 20 characters at most). a() or a(,) is an "
            "array parameter (always by reference; UBOUND gives its size). DIM inside a SUB "
            "declares local variables. EXIT SUB leaves it.",
            "SUB box(x AS INTEGER, y AS INTEGER)\n  BOX x, y, x + 9, y + 9 FILL\nEND SUB\nbox 10, 20"),
    "FUNCTION": ("FUNCTION name [([BYVAL | BYREF] param [()] AS type, ...)] AS type\n  ...\n  RETURN value\nEND FUNCTION",
                 "Defines a function, used in expressions. RETURN gives its value. A function "
                 "returning a STRING may have a name ending with $.",
                 "FUNCTION square(n AS INTEGER) AS LONG\n  RETURN n * n\nEND FUNCTION\nPRINT square(12)"),
    "BYREF": ("SUB name(BYREF param AS type)",
              "The parameter is the caller's variable itself: changing it changes the caller's "
              "variable. The argument must be a variable, an array element or a field of the "
              "same type (not a calculation).",
              "SUB double(BYREF n AS INTEGER)\n  n = n * 2\nEND SUB\ndouble score"),
    "BYVAL": ("SUB name(BYVAL param AS type)",
              "The parameter is a copy: the SUB can change it, the caller's variable stays the "
              "same. Numbers are BYVAL without keyword; BYVAL makes a STRING or a TYPE changeable "
              "(a copy). BYVAL t AS STRING * n: the copy keeps n characters at most.",
              "SUB show(BYVAL t AS STRING)\n  t = UCASE$(t)\n  PRINT t\nEND SUB"),
    "UBOUND": ("UBOUND(array [, dimension])",
               "The largest index of an array (of the dimension 1, 2...): mostly used with an "
               "array parameter, whose size depends on the caller.",
               "FUNCTION total(a() AS INTEGER) AS LONG\n  DIM k AS INTEGER, t AS LONG\n  FOR k = 0 TO UBOUND(a)\n    t += a(k)\n  NEXT\n  RETURN t\nEND FUNCTION"),
    "LBOUND": ("LBOUND(array [, dimension])", "The smallest index of an array: always 0 in Basic89.",
               "FOR k = LBOUND(a) TO UBOUND(a)"),
    "RETURN": ("RETURN value", "Leaves a FUNCTION and gives its value.",
               "FUNCTION sign(n AS INTEGER) AS INTEGER\n  IF n < 0 THEN RETURN -1\n  RETURN 1\nEND FUNCTION"),
    "END": ("END  |  END IF / END SUB / END FUNCTION / END SELECT / END TYPE / END IMAGE",
            "END alone stops the program (also from a SUB or FUNCTION). Followed by a word, it "
            "closes a block.", "IF lives = 0 THEN END"),
    "EXIT": ("EXIT FOR | DO | WHILE | SUB | FUNCTION",
             "Leaves the innermost loop of that kind, or the SUB/FUNCTION.",
             "FOR i = 0 TO 9\n  IF a(i) = 0 THEN EXIT FOR\nNEXT"),
    "INCLUDE": ("INCLUDE \"file.b89\"",
                "Inserts another file (path relative to the file that includes it). A file "
                "included several times is read once.", "INCLUDE \"lib/sprites.b89\""),
    "CALL": ("CALL name(arguments)", "Calls a SUB (the same as writing its name and arguments).",
             "CALL box(10, 20)"),
    "REM": ("REM comment   or   ' comment", "A comment, up to the end of the line.",
            "' this is a comment"),
    # ------------------------------------------------------------ control
    "IF": ("IF condition THEN\n  ...\nELSEIF condition THEN\n  ...\nELSE\n  ...\nEND IF\n\n"
           "IF condition THEN statement [ELSE statement]",
           "Runs statements when a condition is true (not 0). On one line, no END IF.",
           "IF x < 0 THEN\n  x = 0\nELSEIF x > 159 THEN\n  x = 159\nEND IF"),
    "SELECT": ("SELECT CASE value\n  CASE 1, 2\n  CASE 3 TO 9\n  CASE IS > 100\n  CASE ELSE\nEND SELECT",
               "Chooses statements by value. A CASE can list values, ranges (TO) and "
               "comparisons (IS). Works with numbers and STRINGs.",
               "SELECT CASE key\n  CASE 1: PRINT \"one\"\n  CASE 2 TO 5: PRINT \"a few\"\n  CASE ELSE: PRINT \"many\"\nEND SELECT"),
    "FOR": ("FOR counter = start TO end [STEP step]\n  ...\nNEXT [counter]",
            "Repeats with a counter going from start to end (end included). STEP can be "
            "negative or FIXED.", "FOR i = 10 TO 0 STEP -2\n  PRINT i\nNEXT"),
    "DO": ("DO [WHILE | UNTIL condition]\n  ...\nLOOP [WHILE | UNTIL condition]",
           "Repeats while (WHILE) or until (UNTIL) a condition, tested at the start or at the "
           "end. DO ... LOOP without condition repeats until EXIT DO or END.",
           "DO\n  ...\nLOOP UNTIL KEYDOWN(KEY_ESC)"),
    "WHILE": ("WHILE condition\n  ...\nWEND", "Repeats while the condition is true.",
              "WHILE n > 1\n  n = n \\ 2\nWEND"),
    # ------------------------------------------------------------ text
    "PRINT": ("PRINT [value] [; value] [, value] [;]",
              "Writes text and numbers at the text position. ; joins the values, , adds a "
              "space, a final ; stays on the same line.",
              "PRINT \"Score \"; score; \"  Lives \"; lives"),
    "INPUT": ("INPUT [\"prompt\";] variable",
              "Waits for text or a number typed on the keyboard (ENTER to end).",
              "INPUT \"Your name? \"; name"),
    "CLS": ("CLS", "Clears the screen (or the hidden screen) and puts the text position at the top left.", "CLS"),
    "LOCATE": ("LOCATE row, column",
               "Moves the text position (rows 1 to 12, columns 1 to 26, in 6x8 characters).",
               "LOCATE 1, 1\nPRINT \"Score \"; score"),
    # ------------------------------------------------------------ screen
    "SCREEN": ("SCREEN DIRECT | BUFFERED | GRAY4 [BUFFERED]",
               "DIRECT: drawing goes to the screen at once. BUFFERED: drawing goes to a hidden "
               "screen, shown by FLIP (no flicker). GRAY4: 4 shades of gray.",
               "SCREEN GRAY4 BUFFERED\nDO\n  CLS\n  ...\n  FLIP\n  WAITFRAME 32\nLOOP"),
    "FLIP": ("FLIP", "Shows the hidden screen (SCREEN BUFFERED or GRAY4 BUFFERED).", "FLIP"),
    "COLOR": ("COLOR color", "Default color of the drawings: WHITE, LIGHTGRAY, DARKGRAY, BLACK or XOR. "
              "In black and white, every color but WHITE draws black.", "COLOR DARKGRAY"),
    "PSET": ("PSET x, y [, color]", "Draws a pixel (x 0 to 159, y 0 to 99).", "PSET 80, 50"),
    "LINE": ("LINE x1, y1, x2, y2 [, color]", "Draws a line (clipped to the screen).", "LINE 0, 95, 159, 95, DARKGRAY"),
    "BOX": ("BOX x1, y1, x2, y2 [, color] [FILL]", "Draws a rectangle, filled with FILL.", "BOX 10, 10, 40, 30, BLACK FILL"),
    "CIRCLE": ("CIRCLE x, y, radius [, color] [FILL]", "Draws a circle, or a disc with FILL.", "CIRCLE 80, 50, 20, LIGHTGRAY FILL"),
    "WIDTH": ("WIDTH(image)", "Width of an IMAGE, in pixels.", "x = 160 - WIDTH(ship)"),
    "HEIGHT": ("HEIGHT(image)", "Height of an IMAGE, in pixels.", "y = 100 - HEIGHT(ship)"),
    # ------------------------------------------------------------ sprites and maps
    "IMAGE": ("IMAGE name\n  \"pixels\"\n  ...\nEND IMAGE",
              "Draws a picture in the source, one row per line: . transparent, w white, "
              ": light gray, + dark gray, # black (or 0 1 2 3). Up to 160x100.",
              "IMAGE star\n  \"..#..\"\n  \".#:#.\"\n  \"#:::#\"\nEND IMAGE"),
    "SPRITE": ("SPRITE image, x, y [, XOR]",
               "Draws an IMAGE with its transparent pixels (clipped to the screen); XOR inverts "
               "the pixels instead (drawn twice, it disappears).", "SPRITE ship, x, 90"),
    "COLLIDE": ("COLLIDE(image1, x1, y1, image2, x2, y2)",
                "TRUE if the two images, drawn at these places, have an opaque pixel in common.",
                "IF COLLIDE(star, sx, sy, basket, bx, 90) THEN score += 1"),
    "TILESET": ("TILESET name = image0, image1, ...",
                "Groups IMAGEs of the same size, used as tiles 0, 1, 2... by MAP (up to 36).",
                "TILESET tiles = wall, floor, door"),
    "MAP": ("MAP array, tileset, scrollx, scrolly",
            "Draws the part of a tile map (2-dimension INTEGER array of tile numbers) seen from "
            "the pixel (scrollx, scrolly) of the map. Negative numbers are empty cells.",
            "MAP maze, tiles, camx, camy"),
    "MAPROW": ("MAPROW array, row, \"text\"",
               "Fills a row of a tile map: 0-9 and a-z are tile numbers, . or a space an empty cell.",
               "MAPROW maze, 0, \"0000000000\"\nMAPROW maze, 1, \"0111201110\""),
    # ------------------------------------------------------------ time and keys
    "WAITFRAME": ("WAITFRAME frames_per_second",
                  "Waits for the next frame: the loop runs at a steady speed.", "WAITFRAME 32"),
    "WAITKEY": ("WAITKEY", "Waits for a key (shows the hidden screen first).", "WAITKEY"),
    "DELAY": ("DELAY milliseconds", "Waits.", "DELAY 500"),
    "KEYDOWN": ("KEYDOWN(KEY_name)",
                "TRUE while the key is held (several keys at once). Keys: KEY_LEFT, KEY_RIGHT, "
                "KEY_UP, KEY_DOWN, KEY_ENTER, KEY_ESC, KEY_F1 to KEY_F5, KEY_2ND, KEY_SHIFT, "
                "KEY_DIAMOND, KEY_ALPHA, KEY_CLEAR, KEY_APPS, KEY_MODE, KEY_HOME.",
                "IF KEYDOWN(KEY_LEFT) AND x > 0 THEN x -= 2"),
    "GETKEY": ("GETKEY()", "Waits for a key and gives its AMS code (13 is ENTER, 264 ESC...).", "k = GETKEY()"),
    "TICKS": ("TICKS", "A counter that goes up 256 times per second.", "t = TICKS\n...\nPRINT (TICKS - t) / 256.0; \" s\""),
    # ------------------------------------------------------------ sound
    "SOUND": ("SOUND frequency, milliseconds",
              "Plays a note on the link port (2.5 mm, earphones with an adapter). Frequency 0: "
              "silence. The program waits during the note.", "SOUND 440, 200"),
    "PLAY": ("PLAY \"notes\"",
             "Plays a tune: notes A-G (# or - after), length 1 to 64 and a dot, R rest, O octave, "
             "> and < octave up/down, L default length, T tempo.",
             "PLAY \"T120 O4 L8 C D E F G2\""),
    "BEEP": ("BEEP", "A short beep.", "BEEP"),
    # ------------------------------------------------------------ saving
    "SAVE": ("SAVE \"name\", variable, ...",
             "Writes the variables (numbers, STRINGs, whole arrays, TYPEs) into a calculator "
             "variable archived in flash memory.", "SAVE \"hiscore\", best"),
    "LOAD": ("LOAD \"name\", variable, ...",
             "Reads variables written by SAVE. Nothing happens if there is no save, or if it was "
             "made with other variables.", "LOAD \"hiscore\", best"),
    "KILL": ("KILL \"name\"", "Deletes a calculator variable (a save).", "KILL \"hiscore\""),
    "EXISTS": ("EXISTS(\"name\")", "TRUE if the calculator variable exists.",
               "IF NOT EXISTS(\"hiscore\") THEN PRINT \"first game\""),
    # ------------------------------------------------------------ numbers
    "RND": ("RND(n)", "A random integer from 0 to n - 1.", "x = RND(160)"),
    "ABS": ("ABS(x)", "Absolute value (integer or FIXED).", "d = ABS(x - target)"),
    "MIN": ("MIN(a, b)", "The smaller of two numbers.", "x = MIN(x + 3, 144)"),
    "MAX": ("MAX(a, b)", "The larger of two numbers.", "x = MAX(x - 3, 0)"),
    "INT": ("INT(x)", "A FIXED or a FLOAT rounded down to an integer.", "PRINT INT(2.7)   ' 2"),
    "ROUND": ("ROUND(x)", "A FIXED or a FLOAT rounded to the nearest integer.", "PRINT ROUND(2.5)   ' 3"),
    "SQR": ("SQR(x)", "Square root (FIXED, or FLOAT for a FLOAT).", "d = SQR(dx * dx + dy * dy)"),
    "SIN": ("SIN(angle)", "Sine of an angle in radians (FIXED, or FLOAT for a FLOAT).", "y = 50 + 30 * SIN(a)"),
    "COS": ("COS(angle)", "Cosine of an angle in radians (FIXED, or FLOAT for a FLOAT).", "x = 80 + 30 * COS(a)"),
    "TAN": ("TAN(angle)", "Tangent of an angle in radians (FLOAT).", "h = d * TAN(a)"),
    "ATN": ("ATN(x)", "Arc tangent, in radians (FLOAT).", "PRINT ATN(1) * 4   ' pi"),
    "EXP": ("EXP(x)", "e to the power x (FLOAT).", "PRINT EXP(1)   ' 2.718281828459"),
    "LOG": ("LOG(x)", "Natural logarithm (FLOAT).", "PRINT LOG(10)"),
    "PI": ("PI", "3.14159 (FIXED).", "a = 2 * PI"),
    "ISIN": ("ISIN(angle)", "Integer sine: angle in 1/256 of a turn, result in 1/16384 (fast, no FIXED).",
             "y = ISIN(a) * 30 \\ 16384"),
    "ICOS": ("ICOS(angle)", "Integer cosine: angle in 1/256 of a turn, result in 1/16384.",
             "x = ICOS(a) * 30 \\ 16384"),
    # ------------------------------------------------------------ text functions
    "LEN": ("LEN(text)", "Number of characters.", "IF LEN(name) = 0 THEN name = \"player\""),
    "LEFT$": ("LEFT$(text, n)", "The first n characters.", "PRINT LEFT$(\"Hello\", 2)   ' He"),
    "RIGHT$": ("RIGHT$(text, n)", "The last n characters.", "PRINT RIGHT$(\"Hello\", 3)   ' llo"),
    "MID$": ("MID$(text, start [, n])", "n characters from position start (1 is the first); all the rest without n.",
             "PRINT MID$(\"Hello\", 2, 3)   ' ell"),
    "UCASE$": ("UCASE$(text)", "In capital letters.", "PRINT UCASE$(\"abc\")"),
    "LCASE$": ("LCASE$(text)", "In small letters.", "IF LCASE$(answer) = \"y\" THEN ..."),
    "INSTR": ("INSTR(text, searched)", "Position of searched in text (1 is the first), 0 if absent.",
              "IF INSTR(line, \"=\") > 0 THEN ..."),
    "CHR$": ("CHR$(code)", "The character of a code.", "PRINT CHR$(65)   ' A"),
    "ASC": ("ASC(text)", "The code of the first character.", "PRINT ASC(\"A\")   ' 65"),
    "STR$": ("STR$(number)", "A number as text.", "PRINT \"x=\" + STR$(x)"),
    "VAL": ("VAL(text)", "The number written in a text (a FLOAT).", "n = VAL(\"42\")"),
    # ------------------------------------------------------------ types and values
    "INTEGER": ("AS INTEGER", "Whole number, 16 bits: -32768 to 32767.", "DIM x AS INTEGER"),
    "LONG": ("AS LONG", "Whole number, 32 bits: about -2 to 2 billion.", "DIM score AS LONG"),
    "BOOLEAN": ("AS BOOLEAN", "TRUE or FALSE.", "DIM alive AS BOOLEAN = TRUE"),
    "FIXED": ("AS FIXED", "Decimal number in fixed point: -32768 to 32767.99998, step 1/65536. "
              "Fast (computed with integers); mixed with integers automatically.",
              "DIM speed AS FIXED = 0.75"),
    "FLOAT": ("AS FLOAT",
              "Decimal number in floating point, the TI's own (BCD): about 14 significant digits, "
              "up to 1E999, exact like the TI-Basic (0.1 * 3 = 0.3) but slower than FIXED. A "
              "FLOAT in a calculation makes it FLOAT; numbers written with a point keep their "
              "full precision with a FLOAT; 1.5E3 is a FLOAT.",
              "DIM x AS FLOAT = 3.14159265358979\nPRINT SQR(2.0) * 1E10"),
    "STRING": ("AS STRING [* n]", "Text, up to 255 characters (or n). + joins texts.",
               "DIM name AS STRING * 12"),
    "TRUE": ("TRUE / FALSE", "The values 1 and 0.", "done = FALSE"),
    "WHITE": ("WHITE, LIGHTGRAY, DARKGRAY, BLACK, XOR",
              "Colors of the drawings (gray shades in SCREEN GRAY4).", "BOX 0, 0, 20, 20, LIGHTGRAY FILL"),
    "OPERATORS": ("+  -  *  /  \\  MOD   =  <>  <  >  <=  >=   AND  OR  NOT   +=  -=  *=",
                  "\\ is the integer division; / between two integers is also an integer "
                  "division (use a FIXED for decimals); MOD is the remainder. AND, OR, NOT "
                  "combine conditions. + also joins STRINGs.",
                  "IF x MOD 2 = 0 AND NOT done THEN count += 1"),
}

# Words that show the help of another entry
ALIASES = {
    "THEN": "IF", "ELSE": "IF", "ELSEIF": "IF", "CASE": "SELECT", "IS": "SELECT",
    "NEXT": "FOR", "TO": "FOR", "STEP": "FOR", "LOOP": "DO", "UNTIL": "DO", "WEND": "WHILE",
    "AS": "DIM", "FALSE": "TRUE", "LIGHTGRAY": "WHITE", "DARKGRAY": "WHITE", "BLACK": "WHITE",
    "XOR": "WHITE", "FILL": "BOX", "BUFFERED": "SCREEN", "DIRECT": "SCREEN", "GRAY4": "SCREEN",
    "AND": "OPERATORS", "OR": "OPERATORS", "NOT": "OPERATORS", "MOD": "OPERATORS",
}


def lookup(word):
    """(name, (syntax, description, example)) for a word of a program, or None."""
    w = word.upper()
    if w.startswith("KEY_"):
        w = "KEYDOWN"
    w = ALIASES.get(w, w)
    return (w, HELP[w]) if w in HELP else None
