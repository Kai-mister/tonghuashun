// Android arm64 shell entry for the CPython Android distribution.
.global _start
.type _start,%function
_start:
    mov x0, sp
    mov x1, xzr
    adrp x2, :got:Py_BytesMain
    ldr x2, [x2, :got_lo12:Py_BytesMain]
    adrp x3, constructors
    add x3, x3, :lo12:constructors
    b __libc_init
.data
.align 3
constructors:
    .quad 0,0,0
