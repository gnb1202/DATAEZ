"""Exact shared formula evaluation, independent of grouping and SQL."""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fastapi import HTTPException


def evaluate(definition, left, right):
    values = [None if value is None else Decimal(value) for value in [left, right]]
    if any(value is not None and not value.is_finite() for value in values):
        raise HTTPException(422, '정상적인 숫자가 아닌 집계가 있어 계산을 중단했습니다.')
    values = [value.copy_abs() if value is not None and operand.absolute else value
              for value, operand in zip(values, [definition.left, definition.right])]
    left, right = values
    if left is None or right is None:
        return values, None, '집계할 데이터가 없는 항목이 있습니다.'
    if definition.operation != 'difference' and right == 0:
        return values, None, '분모가 0이어서 계산할 수 없습니다.'
    precision = max(50, max(value.adjusted() for value in values)-min(value.as_tuple().exponent for value in values)+20)
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_HALF_EVEN
        if definition.operation == 'difference':
            value = left-right
        else:
            value = (left-right)/right.copy_abs()*100 if definition.operation == 'percent_change' else left/right*(100 if definition.as_percent else 1)
            value = value.quantize(Decimal('0.0001'))
    return values, value, None


def result_unit(definition):
    return definition.left.unit if definition.operation == 'difference' else ('percent' if definition.as_percent else 'number')


def calculation_label(definition):
    def label(operand):
        return f'|{operand.label}|' if operand.absolute else operand.label
    a, b = label(definition.left), label(definition.right)
    return f'{a} − {b}' if definition.operation == 'difference' else (
        f'({a} − {b}) ÷ |{b}| × 100' if definition.operation == 'percent_change' else f'{a} ÷ {b}'+(' × 100' if definition.as_percent else ''))
