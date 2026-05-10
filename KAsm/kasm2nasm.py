#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
import os
import subprocess
import argparse
import tempfile
from pathlib import Path

VERSION = "1.0"

FUNC_MNEM = {
    "переслать": "mov", "переслать_расширить": "movsx", "переслать_обнулить": "movzx",
    "сложить": "add", "вычесть": "sub", "умножить": "imul", "умножить_беззнак": "mul",
    "разделить": "idiv", "разделить_беззнак": "div", "инкремент": "inc", "декремент": "dec",
    "отрицание": "neg", "и": "and", "или": "or", "исключающее": "xor", "не": "not",
    "сдвиг_влево": "shl", "сдвиг_вправо": "shr", "сдвиг_вправо_знак": "sar",
    "вращать_влево": "rol", "вращать_вправо": "ror",
    "вращать_влево_через_перенос": "rcl", "вращать_вправо_через_перенос": "rcr",
    "положить_стек": "push", "снять_стек": "pop",
    "вызвать": "call", "вернуться": "ret",
    "перейти": "jmp", "перейти_равно": "je", "перейти_не_равно": "jne",
    "перейти_больше": "jg", "перейти_меньше": "jl",
    "перейти_больше_равно": "jge", "перейти_меньше_равно": "jle",
    "сравнить": "cmp", "системный_вызов": "syscall",
    "нет_операции": "nop", "останов": "hlt",
}

DIRECTIVES = {
    "#глобальная": "global",
    "#секция": "section",
    "#выравнивание": "align",
    "#данные байт": "db", "#данные слово": "dw",
    "#данные двойное_слово": "dd", "#данные четверное_слово": "dq",
    "#байт": "db", "#слово": "dw", "#двойное": "dd", "#четверное": "dq",
}

def translate_operand(op: str) -> str:
    # Удаляем точки перед именами регистров и метками, но не везде
    return re.sub(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', r'\1', op)

def parse_simple_expression(expr: str):
    expr = expr.strip()
    ops = ['<<<c', '>>>c', '<<<', '>>>', '<<', '>>', '+', '-', '*', '/', '%', '&', '|', '^']
    for op in ops:
        parts = expr.split(op, 1)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            if left and right:
                return (left, op, right)
    return None

def remove_comment(line: str) -> str:
    if '//' in line:
        line = line.split('//')[0]
    # Многострочные комментарии не обрабатываем для простоты
    return line.rstrip()

def translate_line(line: str, line_num: int) -> str:
    line = remove_comment(line).strip()
    if not line:
        return ""

    # Метка-блок
    m = re.match(r'^метка\s+([\w.]+)\s*\{', line)
    if m:
        return f"{m.group(1)}:"
    if line == "}":
        return ""

    # Функциональный стиль
    m = re.match(r'^(\w+)\((.*)\);?$', line)
    if m:
        mnem, args = m.group(1), m.group(2).strip()
        if mnem in FUNC_MNEM:
            nasm_mnem = FUNC_MNEM[mnem]
            if args:
                nasm_args = ", ".join(translate_operand(a) for a in args.split(',') if a.strip())
            else:
                nasm_args = ""
            return f"{nasm_mnem} {nasm_args}".strip()
        raise SyntaxError(f"Строка {line_num}: неизвестная мнемоника '{mnem}'")

    # Операторный стиль
    if re.search(r'\.\w+', line):
        # --- Простое присваивание ---
        m = re.match(r'^([.\w]+)\s*=\s*(.+);$', line)
        if m:
            dst = translate_operand(m.group(1))
            src_raw = m.group(2).strip()

            # 1) Пробуем распознать арифметическое выражение (включая сдвиги)
            expr = parse_simple_expression(src_raw)
            if expr:
                left, op, right = expr
                left_op = translate_operand(left)
                right_op = translate_operand(right)
                nasm_op = {
                    '+': 'add', '-': 'sub', '*': 'imul', '/': 'idiv', '%': '???',
                    '&': 'and', '|': 'or', '^': 'xor',
                    '<<': 'shl', '>>': 'shr', '<<<': 'rol', '>>>': 'ror',
                    '<<<c': 'rcl', '>>>c': 'rcr'
                }.get(op)
                if not nasm_op:
                    raise SyntaxError(f"Строка {line_num}: неподдерживаемый оператор '{op}'")
                if dst == left_op:
                    return f"{nasm_op} {dst}, {right_op}"
                else:
                    return f"mov {dst}, {left_op}\n{nasm_op} {dst}, {right_op}"

            # 2) Если не арифметика — проверим на сравнение (но только если нет сдвигов)
            #    Используем регулярку, которая НЕ ловит << и >>
            comp_match = re.match(r'^(.+?)\s*(<=|>=|==|!=|(?<![<>])<(?![<>])|(?<![<>])>(?![<>]))\s*(.+)$', src_raw)
            if comp_match:
                left = translate_operand(comp_match.group(1).strip())
                op = comp_match.group(2)
                right = translate_operand(comp_match.group(3).strip())

                if dst not in ('al', 'bl', 'cl', 'dl', 'ah', 'bh', 'ch', 'dh'):
                    raise SyntaxError(
                        f"Строка {line_num}: результат сравнения можно записывать только в 8-битный регистр, не в '{dst}'")

                setcc_map = {
                    '<': 'setl',
                    '>': 'setg',
                    '==': 'sete',
                    '<=': 'setle',
                    '>=': 'setge',
                    '!=': 'setne'
                }
                setcc = setcc_map[op]
                return f"cmp {left}, {right}\n{setcc} {dst}"

            # 3) Иначе — простое mov
            src = translate_operand(src_raw)
            return f"mov {dst}, {src}"

        # Составное присваивание
        m = re.match(r'^([.\w]+)\s*([+\-*/%&|^])\=(.+);$', line)
        if m:
            dst = translate_operand(m.group(1))
            op = m.group(2)
            src = translate_operand(m.group(3))
            op_map = {'+': 'add', '-': 'sub', '*': 'imul', '&': 'and', '|': 'or', '^': 'xor'}
            if op in op_map:
                return f"{op_map[op]} {dst}, {src}"
            raise SyntaxError(f"Строка {line_num}: неподдерживаемый составной оператор '{op}='")

        # Вращение с присваиванием
        for op_kasm, op_nasm in [('<<<=c', 'rcl'), ('>>>=c', 'rcr'), ('<<<=', 'rol'), ('>>>=', 'ror')]:
            m = re.match(rf'^([.\w]+)\s*{op_kasm}\s*(.+);$', line)
            if m:
                dst = translate_operand(m.group(1))
                cnt = translate_operand(m.group(2))
                return f"{op_nasm} {dst}, {cnt}"

    # Директивы
    for k, v in DIRECTIVES.items():
        if line.startswith(k):
            rest = line[len(k):].strip()
            if "байт" in k or k == "#байт": return f"db {rest}"
            if "слово" in k: return f"dw {rest}"
            if "двойное" in k: return f"dd {rest}"
            if "четверное" in k: return f"dq {rest}"
            if k == "#выравнивание": return f"align {rest}"
            if k == "#секция":
                if rest in ("текст", "код"): return "section .text"
                if rest in ("данные", "дата"): return "section .data"
                return f"section {rest}"
            return f"{v} {rest}".strip()

    # Если ничего не подошло – синтаксическая ошибка
    raise SyntaxError(f"Line {line_num}: unknown KAsm construction: {line}")

def translate_kasm(source: str) -> str:
    lines = source.splitlines()
    out_lines = []
    for i, line in enumerate(lines, start=1):
        try:
            tl = translate_line(line, i)
            if tl:
                out_lines.extend(tl.split('\n'))
        except SyntaxError as e:
            sys.stderr.write(f"{e}\n")
            sys.exit(1)
    return "\n".join(out_lines).rstrip() + "\n"

def main():
    parser = argparse.ArgumentParser(description="KAsm to NASM translator and compiler")
    parser.add_argument("input", help="Input .kasm file")
    parser.add_argument("-o", "--output", help="Output binary file")
    parser.add_argument("-c", "--code-output", help="Output NASM source (or '-' for stdout)")
    parser.add_argument("--nasm-args", nargs=argparse.REMAINDER, help="Arguments after -- are passed to nasm")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    if args.version:
        print(f"kasm2nasm version {VERSION}")
        sys.exit(0)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.stderr.write(f"Error: file '{input_path}' not found\n")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        kasm_text = f.read()

    nasm_text = translate_kasm(kasm_text)

    if args.code_output:
        if args.code_output == "-":
            sys.stdout.write(nasm_text)
        else:
            with open(args.code_output, "w", encoding="utf-8") as f:
                f.write(nasm_text)
        sys.exit(0)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".asm", delete=False, encoding="utf-8") as tmp:
        tmp.write(nasm_text)
        tmp_asm = tmp.name

    output_bin = args.output if args.output else input_path.with_suffix(".bin")
    nasm_cmd = ["nasm"]
    if args.nasm_args:
        nasm_cmd.extend(args.nasm_args)
    else:
        nasm_cmd.extend(["-f", "bin", "-o", str(output_bin)])
    if "-o" not in nasm_cmd and output_bin:
        nasm_cmd.extend(["-o", str(output_bin)])
    nasm_cmd.append(tmp_asm)

    try:
        subprocess.run(nasm_cmd, check=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"NASM failed with exit code {e.returncode}\n")
        sys.stderr.write(f"Command: {' '.join(nasm_cmd)}\n")
        sys.stderr.write(f"Temporary ASM file left at: {tmp_asm}\n")
        sys.exit(e.returncode)
    except FileNotFoundError:
        sys.stderr.write("Error: nasm not found in PATH\n")
        sys.exit(1)

    os.unlink(tmp_asm)
    sys.stdout.write(f"Compiled {input_path} -> {output_bin}\n")
    sys.exit(0)

if __name__ == "__main__":
    main()