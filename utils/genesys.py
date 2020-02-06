import random


class Result:
    def __init__(self, advantages=0, successs=0, triumphs=0):
        self.advantages = advantages
        self.successs = successs
        self.triumphs = triumphs

    def __repr__(self):
        return (
            f"{type(self).__name__}"
            f"({self.advantages}, {self.successs}, {self.triumphs})"
        )

    def __str__(self):
        ret = []

        if self.successs > 0:
            s = "s" if self.successs > 1 else ""
            ret.append(f"{self.successs} success{s}")
        elif self.successs < 0:
            failures = -self.successs
            s = "s" if failures > 1 else ""
            ret.append(f"{failures} failure{s}")

        if self.advantages > 0:
            s = "s" if self.advantages > 1 else ""
            ret.append(f"{self.advantages} advantage{s}")
        elif self.advantages < 0:
            disadvantages = -self.advantages
            s = "s" if disadvantages > 1 else ""
            ret.append(f"{disadvantages} disadvantage{s}")

        if self.triumphs > 0:
            s = "s" if self.triumphs > 1 else ""
            ret.append(f"{self.triumphs} triumph{s}")
        elif self.triumphs < 0:
            despairs = -self.triumphs
            s = "s" if despairs > 1 else ""
            ret.append(f"{despairs} despair{s}")

        if ret:
            ret = f'{", ".join(ret)}.'
        else:
            ret = "Wash."
        return ret

    def __add__(self, other):
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

    def __mul__(self, other):
        return type(self)(
            self.advantages * other, self.successs * other, self.triumphs * other
        )

    __rmul__ = __mul__

    def __neg__(self):
        return type(self)(-self.advantages, -self.successs, -self.triumphs)


class Force:
    def __init__(self, light=0, dark=0):
        self.light = light
        self.dark = dark

    def __repr__(self):
        return f"{type(self).__name__}({self.light}, {self.dark})"

    def __str__(self):
        ret = []
        if self.light:
            ret.append(f"{self.light} light side")
        if self.dark:
            ret.append(f"{self.dark} dark side")
        if not ret:
            ret = "Wash."
        else:
            ret = ", ".join(ret) + "."
        return ret

    def __add__(self, other):
        if isinstance(other, Force):
            return type(self)(self.light + other.light, self.dark + other.dark)
        elif isinstance(other, int):
            return type(self)(self.light + other, self.dark + other)
        return NotImplemented

    __radd__ = __add__

    def __mul__(self, other):
        return type(self)(self.light * other, self.dark * other)

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

dice = {
    "boost": (wash, wash, success, success + advantage, 2 * advantage, advantage),
    "setback": (wash, wash, failure, failure, disadvantage, disadvantage),
    "ability": (
        wash,
        success,
        success,
        2 * success,
        2 * advantage,
        advantage,
        success + advantage,
        2 * advantage,
    ),
    "difficulty": (
        wash,
        failure,
        2 * failure,
        disadvantage,
        disadvantage,
        disadvantage,
        2 * disadvantage,
        failure + disadvantage,
    ),
    "proficiency": (
        wash,
        success,
        success,
        2 * success,
        2 * success,
        advantage,
        success + advantage,
        success + advantage,
        success + advantage,
        advantage * 2,
        advantage * 2,
        triumph,
    ),
    "challenge": (
        wash,
        failure,
        failure,
        2 * failure,
        2 * failure,
        disadvantage,
        disadvantage,
        failure + disadvantage,
        failure + disadvantage,
        2 * disadvantage,
        2 * disadvantage,
        despair,
    ),
    "force": (
        dark,
        dark,
        dark,
        dark,
        dark,
        dark,
        2 * dark,
        light,
        light,
        2 * light,
        2 * light,
        2 * light,
    ),
}


def genesysroller(**kwargs):
    if "force" in kwargs:
        if len(kwargs) > 1:
            raise ValueError
        return sum(random.choice(dice["force"]) for _ in range(kwargs["force"]))
    result = Result()
    for die, times in kwargs.items():
        result += sum(random.choice(dice[die]) for _ in range(times))
    return result
