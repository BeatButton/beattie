from __future__ import annotations

import random
from numbers import Real
from typing import Any, Union


class Result:
    def __init__(self, advantages: int = 0, successs: int = 0, triumphs: int = 0):
        self.advantages = advantages
        self.successs = successs
        self.triumphs = triumphs

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"({self.advantages}, {self.successs}, {self.triumphs})"
        )

    def __str__(self) -> str:
        out = []

        if self.successs > 0:
            s = "es" if self.successs > 1 else ""
            out.append(f"{self.successs} success{s}")
        elif self.successs < 0:
            failures = -self.successs
            s = "s" if failures > 1 else ""
            out.append(f"{failures} failure{s}")

        if self.advantages > 0:
            s = "s" if self.advantages > 1 else ""
            out.append(f"{self.advantages} advantage{s}")
        elif self.advantages < 0:
            disadvantages = -self.advantages
            s = "s" if disadvantages > 1 else ""
            out.append(f"{disadvantages} disadvantage{s}")

        if self.triumphs > 0:
            s = "s" if self.triumphs > 1 else ""
            out.append(f"{self.triumphs} triumph{s}")
        elif self.triumphs < 0:
            despairs = -self.triumphs
            s = "s" if despairs > 1 else ""
            out.append(f"{despairs} despair{s}")

        if out:
            ret = f'{", ".join(out)}.'
        else:
            ret = "Wash."
        return ret

    def __add__(self, other: Any) -> Result:
        if isinstance(other, Result):
            return type(self)(
                self.advantages + other.advantages,
                self.successs + other.successs,
                self.triumphs + other.triumphs,
            )
        elif isinstance(other, int):
            return type(self)(
                self.advantages + other, self.successs + other, self.triumphs + other
            )
        else:
            return NotImplemented

    __radd__ = __add__

    def __mul__(self, other: Any) -> Result:
        if isinstance(other, Real):
            return type(self)(
                self.advantages * other, self.successs * other, self.triumphs * other
            )
        else:
            return NotImplemented

    __rmul__ = __mul__

    def __neg__(self) -> Result:
        return type(self)(-self.advantages, -self.successs, -self.triumphs)


class Force:
    def __init__(self, light: int = 0, dark: int = 0):
        self.light = light
        self.dark = dark

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.light}, {self.dark})"

    def __str__(self) -> str:
        out = []
        if self.light:
            out.append(f"{self.light} light side")
        if self.dark:
            out.append(f"{self.dark} dark side")
        if not out:
            ret = "Wash."
        else:
            ret = ", ".join(out) + "."
        return ret

    def __add__(self, other: Any) -> Force:
        if isinstance(other, Force):
            return type(self)(self.light + other.light, self.dark + other.dark)
        elif isinstance(other, int):
            return type(self)(self.light + other, self.dark + other)
        else:
            return NotImplemented

    __radd__ = __add__

    def __mul__(self, other: Any) -> Force:
        if isinstance(other, Real):
            return type(self)(self.light * other, self.dark * other)
        else:
            return NotImplemented

    __rmul__ = __mul__


wash = Result()
advantage = Result(advantages=1)
success = Result(successs=1)
triumph = Result(triumphs=1)
disadvantage = -advantage
failure = -success
despair = -triumph
light = Force(light=1)
dark = Force(dark=1)

die_names = {
    "b": "boost",
    "s": "setback",
    "a": "ability",
    "d": "difficulty",
    "p": "proficiency",
    "c": "challenge",
    "f": "force",
}

dice: dict[str, tuple[Union[Result, Force], ...]] = {
    "boost": (wash, wash, success, success + advantage, 2 * advantage, advantage),
    "setback": (wash, wash, failure, failure, disadvantage, disadvantage),
    "ability": (
        wash,
        advantage,
        2 * advantage,
        2 * advantage,
        success + advantage,
        success,
        success,
        2 * success,
    ),
    "difficulty": (
        wash,
        disadvantage,
        disadvantage,
        disadvantage,
        2 * disadvantage,
        failure + disadvantage,
        failure,
        2 * failure,
    ),
    "proficiency": (
        wash,
        advantage,
        advantage * 2,
        advantage * 2,
        success + advantage,
        success + advantage,
        success + advantage,
        success,
        success,
        2 * success,
        2 * success,
        triumph,
    ),
    "challenge": (
        wash,
        disadvantage,
        disadvantage,
        2 * disadvantage,
        2 * disadvantage,
        failure + disadvantage,
        failure + disadvantage,
        failure,
        failure,
        2 * failure,
        2 * failure,
        despair,
    ),
    "force": (
        2 * dark,
        dark,
        dark,
        dark,
        dark,
        dark,
        dark,
        light,
        light,
        2 * light,
        2 * light,
        2 * light,
    ),
}


def genesysroller(**kwargs: int) -> Union[Result, Force]:
    result: Union[Result, Force]
    if "force" in kwargs:
        if len(kwargs) > 1:
            raise ValueError
        result = Force()
        for _ in range(kwargs["force"]):
            result += random.choice(dice["force"])
        return result
    result = Result()
    for die, times in kwargs.items():
        result += sum(random.choice(dice[die]) for _ in range(times))
    return result
