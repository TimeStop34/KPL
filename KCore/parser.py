#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import pprint
from enum import Enum
from lexer import Lexer, TokenType, Token

# ------------------------------------------------------------
# Узлы AST
# ------------------------------------------------------------
class ASTNode:
    def __init__(self, kind, **kwargs):
        self.kind = kind
        for k, v in kwargs.items():
            setattr(self, k, v)
    def __repr__(self):
        attrs = ', '.join(f"{k}={v!r}" for k, v in self.__dict__.items() if k != 'kind')
        return f"{self.kind}({attrs})"

# ------------------------------------------------------------
# Исключение
# ------------------------------------------------------------
class ParseError(Exception):
    def __init__(self, msg, token):
        self.token = token
        super().__init__(f"{msg} at {token.line}:{token.column}")

# ------------------------------------------------------------
# Тип конструкции
# ------------------------------------------------------------
class ConstructionType(Enum):
    FUNCTION = 'FUNCTION' # Сделал
    FUNCTION_CALL = 'FUNCTION_CALL' # <- Завтра
    VARIABLE_STATEMENT = 'VARIABLE_STATEMENT' # <- Завтра
    VARIABLE = 'VARIABLE' # Сделал
    STRUCT = 'STRUCT' # Сделал
    BLOCK = 'BLOCK' # Сделал
    BLOCK_INSTRUCTION = 'BLOCK_INSTRUCTION'
    ASSEMBLY_BLOCK = 'ASSEMBLY_BLOCK' # Сделал, не сделал встроенный ассемблер только (не как вставка)
    KEYWORD = 'KEYWORD' # Сделал
    PREPROCESSOR = 'PREPROCESSOR' # <- позже, maybe завтра. Завтра - решение проблемы
    UNKNOWN = 'UNKNOWN' # Сделал

# ------------------------------------------------------------
# Парсер
# ------------------------------------------------------------
class KParser:
    def __init__(self, tokens_from_lexer, source_text=''):
        self.tokens = tokens_from_lexer
        self.pos = 0
        self.source_text = source_text
        self.parsing = False
        self.ast = []

    def current_token(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        else:
            raise ParseError(f"Unexpected EOF on {self.pos}", None)

    def next_token(self) -> Token:
        return self.token_on_offset(1)

    def token_on_offset(self, offset) -> Token:
        if self.pos + offset < len(self.tokens):
            token = self.tokens[self.pos + offset]
            return token
        else:
            raise ParseError(f"Unexpected EOF on {self.pos+offset}", None)

    def parse_modificators(self, allow_reference=False) -> str:
        """Разбирает модификаторы после основного типа: { '*' } [ '&' ]
           Возвращает строку с модификаторами через пробел, например '* * &'
        """
        parts = []
        # Звёздочки
        while self.current_token().type == TokenType.OPERATOR and self.current_token().value == '*':
            parts.append('*')
            self.consume()
        # Ссылка (только одна, только если разрешена)
        if allow_reference and self.current_token().type == TokenType.OPERATOR and self.current_token().value == '&':
            parts.append('&')
            self.consume()
        return ' '.join(parts)

    def consume(self, expected_value=None, expected_type=None) -> Token:
        prev_token = self.current_token()
        if prev_token is None:
            raise Exception("WTF?")
        else:
            if expected_type is not None:
                if isinstance(expected_type, list):
                    if prev_token.type not in expected_type:
                        raise ParseError(
                            f"Expected type mismatch, required - {expected_type}, having - {prev_token.type}",
                            prev_token)
                elif prev_token.type != expected_type:
                    raise ParseError(f"Expected type mismatch, required - {expected_type}, having - {prev_token.type}",
                                     prev_token)

                if expected_value is not None:
                    if prev_token.value != expected_value:
                        raise ParseError(
                            f"Expected value mismatch, required - {expected_value}, having - {prev_token.value}",
                            prev_token)
        self.pos += 1
        new_token = self.current_token()
        if new_token is None:
            raise ParseError("Unexpected EOF", prev_token)
        return prev_token

    def consume_until(self, stop_type, stop_value=None) -> list[Token]:
        """
        Потребляет все токены, начиная с текущего, до токена с типом `stop_type`
        (и, если задано `stop_value`, с таким же значением). Стоп-токен не потребляется.
        Возвращает список потреблённых токенов (без стоп-токена).
        """
        consumed = []
        while True:
            tok = self.current_token()
            if tok is None:
                raise ParseError(
                    f"EOF reached before finding {stop_type}" +
                    (f" '{stop_value}'" if stop_value else ""),
                    None
                )
            if tok.type == stop_type and (stop_value is None or tok.value == stop_value):
                break
            consumed.append(tok)
            self.pos += 1
        return consumed

    def _datatype_start(self, allow_reference=False) -> int:
        offset = 0
        # знаковость?
        tok = self.token_on_offset(offset)
        if tok.type == TokenType.DATATYPE and tok.value in ("беззнаковый", "знаковый"):
            offset += 1
            tok = self.token_on_offset(offset)
        # основной тип (обязателен)
        if tok.type not in (TokenType.DATATYPE, TokenType.IDENTIFIER):
            return 0
        offset += 1
        # модификаторы: *, &, [ ... ]
        while True:
            tok = self.token_on_offset(offset)
            if tok.type == TokenType.OPERATOR and tok.value == '*':
                offset += 1
                continue
            if tok.type == TokenType.OPERATOR and tok.value == '&':
                if not allow_reference:
                    return 0  # или break, в зависимости от грамматики
                offset += 1
                continue
            if tok.type == TokenType.PUNCTUATION and tok.value == '[':
                offset += 1  # пропускаем '['
                depth = 1
                while depth > 0:
                    ntok = self.token_on_offset(offset)
                    if ntok.type == TokenType.PUNCTUATION:
                        if ntok.value == '[':
                            depth += 1
                        elif ntok.value == ']':
                            depth -= 1
                    offset += 1
                    if offset > len(self.tokens):
                        return 0  # незакрытая скобка
                continue
            break
        return offset

    def consume_datatype(self, allow_reference=False) -> str:
        """Потребляет полное описание типа: знаковость? основной_тип ( '*' | '&'? | '[' число? ']' )*
           Возвращает строку типа, например 'беззнаковый целое[3] *'
        """
        parts = []
        start_pos = self.pos  # для отладки

        # 1. Знаковость (опционально)
        tok = self.current_token()
        if tok.type == TokenType.DATATYPE and tok.value in ('беззнаковый', 'знаковый'):
            parts.append(tok.value)
            self.consume()

        # 2. Основной тип (обязателен)
        tok = self.current_token()
        if tok.type not in (TokenType.DATATYPE, TokenType.IDENTIFIER):
            raise ParseError(f"Expected data type or identifier, got {tok.type}", tok)
        base = tok.value
        if parts and base in ('битфлаговый', 'логическое'):
            raise ParseError(f"Type '{base}' cannot be signed/unsigned", tok)
        parts.append(base)
        self.consume()

        # 3. Модификаторы (*, &, [])
        while True:
            tok = self.current_token()
            if tok.type == TokenType.OPERATOR and tok.value == '*':
                parts.append('*')
                self.consume()
                continue
            if tok.type == TokenType.OPERATOR and tok.value == '&':
                if not allow_reference:
                    raise ParseError("Reference '&' not allowed here", tok)
                parts.append('&')
                self.consume()
                # После & обычно не идут другие модификаторы (но можно и продолжить, если хотите)
                # Поскольку & только один, после него break
                continue  # или break, решите сами
            if tok.type == TokenType.PUNCTUATION and tok.value == '[':
                # Читаем всё до соответствующей ']'
                bracket_content = self.consume_bracket_pair()
                parts.append(bracket_content)  # например "[3]" или "[]"
                continue
            # Ни один из модификаторов не подошёл – выходим
            break



        return ' '.join(parts)

    def consume_bracket_pair(self) -> str:
        """Потребляет '[' ... ']' и возвращает подстроку, например '[3]' или '[]'."""
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value='[')
        # Собираем содержимое между скобками (может быть число или пусто)
        if self.current_token().type == TokenType.NUMBER:
            dim = self.current_token().value
            self.consume()
        else:
            dim = ''
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value=']')
        return f'[{dim}]'

    def recognize_instruction_construction(self) -> ConstructionType:
        construct = ConstructionType.UNKNOWN
        current_token = self.current_token()
        if current_token.type == TokenType.PREPROC:
            construct = ConstructionType.PREPROCESSOR
        elif current_token.type == TokenType.KEYWORD:
            if current_token.value == 'структура':
                construct = ConstructionType.STRUCT
            elif current_token.value == 'ассемблер':
                construct = ConstructionType.ASSEMBLY_BLOCK
            elif current_token.value in ("если", "иначе", "пока", "для", "сначала", "перебрать", "выбор"):
                construct = ConstructionType.BLOCK_INSTRUCTION
            elif current_token.value in ("вернуть", "выход", "продолжить", "перейти"):
                construct = ConstructionType.KEYWORD
        elif current_token.type == TokenType.PUNCTUATION and current_token.value == "{":
            construct = ConstructionType.BLOCK
        elif current_token.type == TokenType.IDENTIFIER:
            next_token = self.token_on_offset(2)
            if next_token.type == TokenType.PUNCTUATION and next_token.value == "(":
                construct = ConstructionType.FUNCTION_CALL
            elif next_token.type == TokenType.OPERATOR:
                construct = ConstructionType.VARIABLE_STATEMENT
        datatype = self._datatype_start(allow_reference=False)
        print("Token: ", current_token, "Is_datatype_start: ", datatype) 
        if datatype > 0:
            saved_pos = self.pos
            print("Token: ", current_token, "Is_datatype_start: ", datatype)
            self.pos += datatype
            offset2 = self.next_token()
            print("Token: ", offset2)
            if offset2.type == TokenType.PUNCTUATION and offset2.value == "(":
                construct = ConstructionType.FUNCTION
            elif (
                (offset2.type == TokenType.OPERATOR) or
                (offset2.type == TokenType.PUNCTUATION and offset2.value == ";")
            ):
                construct = ConstructionType.VARIABLE
            self.pos = saved_pos
            print("Token: ", self.current_token(), "\nConstruct: ", construct)
        return construct

    # ------------------------- #
    #     v НЕ ДОДЕЛАНО! v      #
    # ------------------------- #
    def parse_preproc(self) -> ASTNode:
        self.consume(expected_type=TokenType.PREPROC)
        name = self.consume(expected_type=TokenType.IDENTIFIER).value
        node = ASTNode(ConstructionType.PREPROCESSOR)
        return node

    def parse_struct(self) -> ASTNode:
        self.consume(expected_type=TokenType.KEYWORD)
        struct_name = self.consume(expected_type=TokenType.IDENTIFIER).value
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value="{")
        struct_params = []
        while True:
            param_type = self.consume_datatype()

            param_name = self.consume(expected_type=TokenType.IDENTIFIER).value

            param_bits = -1
            if self.current_token().type == TokenType.OPERATOR and self.current_token().value == ":":
                self.consume(expected_type=TokenType.OPERATOR, expected_value=":")
                param_bits = self.consume(expected_type=TokenType.NUMBER).value

            self.consume(expected_type=TokenType.PUNCTUATION, expected_value=";")
            struct_params.append({"type": param_type, "name": param_name, "bits": param_bits})

            if self.current_token().type == TokenType.PUNCTUATION and self.current_token().value == "}":
                self.consume(expected_type=TokenType.PUNCTUATION, expected_value="}")
                self.consume(expected_type=TokenType.PUNCTUATION, expected_value=";")
                break

        return ASTNode(ConstructionType.STRUCT, name=struct_name, params=struct_params)

    def parse_variable(self) -> ASTNode:
        var_type = self.consume_datatype()
        name = self.consume(expected_type=TokenType.IDENTIFIER).value

        value = []
        if self.current_token().type == TokenType.OPERATOR and self.current_token().value == "=":
            self.consume(expected_type=TokenType.OPERATOR, expected_value="=")
            value = self.consume_until(TokenType.PUNCTUATION, stop_value=";")

        self.consume(expected_type=TokenType.PUNCTUATION, expected_value=";")

        return ASTNode(ConstructionType.VARIABLE, name=name, type=var_type, value=value)

    def consume_block(self) -> list[ASTNode]:
        ast_list = []
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value="{")
        while True:
            if self.current_token().type == TokenType.PUNCTUATION and self.current_token().value == "}":
                self.consume(expected_type=TokenType.PUNCTUATION, expected_value="}")
                break
            construction_type = self.recognize_instruction_construction()
            ast_list.append(self.parse_instruction(construction_type))
        return ast_list

    def parse_block(self) -> ASTNode:
        block = self.consume_block()
        return ASTNode(ConstructionType.BLOCK, code=block)

    def parse_function(self) -> ASTNode:
        datatype = self.consume_datatype()
        name = self.consume(expected_type=TokenType.IDENTIFIER).value
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value="(")
        parameters = {}
        while True:
            param_type = self.consume_datatype(allow_reference=True)
            param_name = self.consume(expected_type=TokenType.IDENTIFIER).value
            parameters[param_name] = param_type
            if self.current_token().type == TokenType.PUNCTUATION and self.current_token().value == ")":
                self.consume(expected_type=TokenType.PUNCTUATION, expected_value=")")
                break
            else:
                print("token: {}?".format(self.current_token()))
                self.consume(expected_type=TokenType.PUNCTUATION, expected_value=",")

        block = self.consume_block()

        return ASTNode(ConstructionType.FUNCTION, return_datatype=datatype, name=name, parameters=parameters, code=block)

    def parse_assembly_block(self) -> ASTNode:
        self.consume(expected_type=TokenType.KEYWORD, expected_value="ассемблер")
        block = self.consume_until(TokenType.PUNCTUATION, stop_value="}")
        return ASTNode(ConstructionType.ASSEMBLY_BLOCK, assembly=block)

    def parse_keyword(self) -> ASTNode:
        keyword = self.consume(expected_type=TokenType.KEYWORD).value
        arg = None
        if keyword in ("вернуть", "перейти"):
            arg = self.consume()
        return ASTNode(ConstructionType.KEYWORD, keyword=keyword, arg=arg)

    def parse_function_call(self):
        func_name = self.consume(expected_type=TokenType.IDENTIFIER).value
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value="(")
        args = self.consume_until(TokenType.PUNCTUATION, stop_value=")")
        self.consume(expected_type=TokenType.PUNCTUATION, expected_value=";")
        return ASTNode(ConstructionType.FUNCTION, func_name=func_name, args=args)

    def parse_instruction(self, construction_type) -> ASTNode:
        match construction_type:
            case ConstructionType.UNKNOWN:
                raise ParseError("Unknown construction type", self.current_token())
            case ConstructionType.PREPROCESSOR:
                return self.parse_preproc()
            case ConstructionType.STRUCT:
                return self.parse_struct()
            case ConstructionType.VARIABLE:
                return self.parse_variable()
            case ConstructionType.FUNCTION:
                return self.parse_function()
            case ConstructionType.ASSEMBLY_BLOCK:
                return self.parse_assembly_block()
            case ConstructionType.KEYWORD:
                return self.parse_keyword()
            case ConstructionType.BLOCK:
                return self.parse_block()
            case _:
                raise Exception("Не сделал конструкцию -> {} на {}".format(construction_type, self.current_token()))

    def parse(self):
        self.parsing = True
        while self.parsing:
            if self.current_token().type == TokenType.EOF:
                break
            construction_type = self.recognize_instruction_construction()
            self.ast.append(self.parse_instruction(construction_type))

        return self.ast


# ------------------------------------------------------------
if __name__ == '__main__':
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            src = f.read()
    else:
        src = sys.stdin.read()

    lexer = Lexer(src)
    tokens = lexer.tokenize()
    p = KParser(tokens, src)
    try:
        module = p.parse()
        for node in module:
            pprint.pprint(node.__dict__)
    except ParseError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
