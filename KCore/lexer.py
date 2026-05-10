import sys
import re

class TokenType:
    KEYWORD = 'KEYWORD'
    DATATYPE = 'DATATYPE'
    IDENTIFIER = 'IDENTIFIER'
    NUMBER = 'NUMBER'
    STRING = 'STRING'
    OPERATOR = 'OPERATOR'
    PUNCTUATION = 'PUNCTUATION'
    PREPROC = 'PREPROC'
    BOOL = 'BOOL'
    EOF = 'EOF'

class Token:
    def __init__(self, type_, value, line, column, start):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column
        self.start = start          # позиция первого символа в исходной строке
    def __repr__(self):
        return f'Token({self.type}, {self.value!r}, {self.line}:{self.column})'

class Lexer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.length = len(source)

    def error(self, msg):
        raise SyntaxError(f'Lexer error at {self.line}:{self.column}: {msg}')

    def peek(self, offset=0):
        if self.pos + offset >= self.length:
            return '\0'
        return self.source[self.pos + offset]

    def advance(self, n=1):
        for _ in range(n):
            if self.pos < self.length and self.source[self.pos] == '\n':
                self.line += 1
                self.column = 1
            elif self.pos < self.length:
                self.column += 1
            self.pos += 1

    def skip_whitespace(self):
        while self.pos < self.length and self.source[self.pos].isspace():
            self.advance()

    def skip_comment(self):
        if self.peek() == '/' and self.peek(1) == '/':
            self.advance(2)
            while self.pos < self.length and self.peek() != '\n':
                self.advance()
            self.advance()
            return True
        elif self.peek() == '/' and self.peek(1) == '*':
            self.advance(2)
            while self.pos < self.length:
                if self.peek() == '*' and self.peek(1) == '/':
                    self.advance(2)
                    break
                self.advance()
            return True
        return False

    def read_number(self):
        start = self.pos
        if self.peek() == '0':
            if self.peek(1) in ('x', 'X'):
                self.advance(2)
                while self.peek().isalnum() or self.peek() in 'abcdefABCDEF':
                    self.advance()
                return self.source[start:self.pos]
            elif self.peek(1) in ('o', 'O'):
                self.advance(2)
                while self.peek() in '01234567':
                    self.advance()
                return self.source[start:self.pos]
            elif self.peek(1) in ('b', 'B'):
                self.advance(2)
                while self.peek() in '01':
                    self.advance()
                return self.source[start:self.pos]
        dot_seen = False
        while self.pos < self.length:
            ch = self.peek()
            if ch.isdigit():
                self.advance()
            elif ch == '.' and not dot_seen:
                dot_seen = True
                self.advance()
            else:
                break
        if self.peek() in ('e', 'E'):
            self.advance()
            if self.peek() in ('+', '-'):
                self.advance()
            while self.peek().isdigit():
                self.advance()
        return self.source[start:self.pos]

    def read_string(self):
        start = self.pos
        self.advance()
        while self.pos < self.length:
            if self.peek() == '\\':
                self.advance(2)
            elif self.peek() == '"':
                self.advance()
                return self.source[start:self.pos]
            else:
                self.advance()
        self.error("Unterminated string")

    def read_ident_or_keyword(self):
        start = self.pos
        while self.pos < self.length and (self.peek().isalnum() or self.peek() == '_' or (self.peek().isalpha() and ord(self.peek()) > 127)):
            self.advance()
        value = self.source[start:self.pos]

        data_types = {
            'ничто', 'байт', 'короткое', 'целое', 'длинное', 'дробное',
            'десятичное', 'логическое', 'битфлаговый', 'знаковый', 'беззнаковый',
            'истина', 'ложь'
        }
        if value in data_types:
            if value in ('истина', 'ложь'):
                return TokenType.BOOL, value
            return TokenType.DATATYPE, value

        keywords = {
            'если', 'иначе', 'пока', 'для', 'сначала', 'потом_если', 'перебрать', 'выбор',
            'метка', 'по_умолчанию', 'выход', 'продолжить', 'перейти', 'вернуть',
            'структура', 'размер', 'ассемблер', 'из', 'и', 'или', 'не'
        }

        if value in keywords:
            return TokenType.KEYWORD, value
        return TokenType.IDENTIFIER, value

    def read_operator_or_punct(self):
        start = self.pos
        operators = [
            '<<<', '>>>', '<<=', '>>=', '<<<=', '>>>=', '**=', '**', '<=', '>=', '==', '!=',
            '+=', '-=', '*=', '/=', '%=', '\\=', '&=', '|=', '^=', '<<', '>>',
            '++', '--', '->', '::', '&&', '||', '?', ':'
        ]
        for op in operators:
            if self.source.startswith(op, self.pos):
                self.advance(len(op))
                return TokenType.OPERATOR, op

        ch = self.peek()
        if ch in '+-*/%\\&|^~!<>?=':
            self.advance()
            return TokenType.OPERATOR, ch
        elif ch in '();,{}[]#:.':
            self.advance()
            if ch == '#':
                return TokenType.PREPROC, ch
            return TokenType.PUNCTUATION, ch
        else:
            self.error(f"Unknown character: {ch}")
            return None

    def get_next_token(self):
        self.skip_whitespace()
        if self.pos >= self.length:
            return Token(TokenType.EOF, None, self.line, self.column, self.pos)

        # запоминаем начало токена
        start = self.pos

        if self.skip_comment():
            return self.get_next_token()

        ch = self.peek()
        if ch.isdigit() or (ch == '.' and self.peek(1).isdigit()):
            num = self.read_number()
            return Token(TokenType.NUMBER, num, self.line, self.column - len(num), start)
        if ch == '"':
            string = self.read_string()
            return Token(TokenType.STRING, string, self.line, self.column - len(string), start)
        if ch.isalpha() or ch == '_' or (ord(ch) > 127 and ch.isalpha()):
            type_, val = self.read_ident_or_keyword()
            return Token(type_, val, self.line, self.column - len(val), start)
        op_type, op_val = self.read_operator_or_punct()
        return Token(op_type, op_val, self.line, self.column - len(op_val), start)

    def tokenize(self):
        tokens = []
        while True:
            tok = self.get_next_token()
            tokens.append(tok)
            if tok.type == TokenType.EOF:
                break
        return tokens

if __name__ == '__main__':
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            code = f.read()
    else:
        code = sys.stdin.read()

    lexer = Lexer(code)
    for tok in lexer.tokenize():
        print(tok)