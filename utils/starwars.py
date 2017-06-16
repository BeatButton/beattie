import random


class Result:
    def __init__(self, advantages=0, hits=0, triumphs=0):
        self.advantages = advantages
        self.hits = hits
        self.triumphs = triumphs

    def __repr__(self):
        return (f'{type(self).__name__}'
                f'({self.advantages}, {self.hits}, {self.triumphs})')

    def __str__(self):
        ret = []

        if self.hits > 0:
            s = 's' if self.hits > 1 else ''
            ret.append(f'{self.hits} hit{s}')
        elif self.hits < 0:
            misses = -self.hits
            es = 'es' if misses > 1 else ''
            ret.append(f'{misses} miss{es}')

        if self.advantages > 0:
            s = 's' if self.advantages > 1 else ''
            ret.append(f'{self.advantages} advantage{s}')
        elif self.advantages < 0:
            disadvantages = -self.advantages
            s = 's' if disadvantages > 1 else ''
            ret.append(f'{disadvantages} disadvantage{s}')

        if self.triumphs > 0:
            s = 's' if self.triumphs > 1 else ''
            ret.append(f'{self.triumphs} triumph{s}')
        elif self.triumphs < 0:
            despairs = -self.triumphs
            s = 's' if despairs > 1 else ''
            ret.append(f'{despairs} despair{s}')

        if ret:
            ret = f'{", ".join(ret)}.'
        else:
            ret = 'Wash.'
        return ret

    def __add__(self, other):
        if isinstance(other, Result):
            return type(self)(self.advantages + other.advantages,
                              self.hits + other.hits,
                              self.triumphs + other.triumphs)
        elif isinstance(other, int):
            return type(self)(self.advantages + other,
                              self.hits + other,
                              self.triumphs + other)
        else:
            return NotImplemented

    __radd__ = __add__

    def __mul__(self, other):
        return type(self)(self.advantages * other,
                          self.hits * other,
                          self.triumphs * other)

    __rmul__ = __mul__

    def __neg__(self):
        return type(self)(-self.advantages, -self.hits, -self.triumphs)


class Force:
    def __init__(self, light=0, dark=0):
        self.light = light
        self.dark = dark

    def __repr__(self):
        return f'{type(self).__name__}({self.light}, {self.dark})'

    def __str__(self):
        ret = []
        if self.light:
            ret.append(f'{self.light} light side')
        if self.dark:
            ret.append(f'{self.dark} dark side')
        if not ret:
            ret = 'Wash.'
        else:
            ret = ', '.join(ret) + '.'
        return ret

    def __add__(self, other):
        if isinstance(other, Force):
            return type(self)(self.light + other.light,
                              self.dark + other.dark)
        elif isinstance(other, int):
            return type(self)(self.light + other,
                              self.dark + other)
        return NotImplemented

    __radd__ = __add__

    def __mul__(self, other):
        return type(self)(self.light * other, self.dark * other)

    __rmul__ = __mul__


wash = Result()
adv = Result(advantages=1)
hit = Result(hits=1)
triumph = Result(triumphs=1)
dis = -adv
miss = -hit
despair = -triumph
light = Force(light=1)
dark = Force(dark=1)

die_names = {'b': 'boost',
             's': 'setback',
             'a': 'ability',
             'd': 'difficulty',
             'p': 'proficiency',
             'c': 'challenge',
             'f': 'force'}

stardice = {'boost': (wash, wash, hit, hit + adv, 2 * adv, adv),
            'setback': (wash, wash, miss, miss, dis, dis),
            'ability': (wash, hit, hit, 2 * hit, 2 * adv, adv,
                        hit + adv, 2 * adv),
            'difficulty': (wash, miss, 2 * miss, dis, dis, dis,
                           2 * dis, miss + dis),
            'proficiency': (wash, hit, hit, 2 * hit, 2 * hit, adv, hit + adv,
                            hit + adv, hit + adv, adv * 2, adv * 2, triumph),
            'challenge': (wash, miss, miss, 2 * miss, 2 * miss, dis, dis,
                          miss + dis, miss + dis, 2 * dis, 2 * dis, despair),
            'force': (dark, dark, dark, dark, dark, dark, 2 * dark,
                      light, light, 2 * light, 2 * light, 2 * light),
            }


def starroller(**kwargs):
    if 'force' in kwargs:
        if len(kwargs) > 1:
            raise ValueError
        return sum(random.choice(stardice['force'])
                   for _ in range(kwargs['force']))
    result = Result()
    for die, times in kwargs.items():
        result += sum(random.choice(stardice[die])
                      for _ in range(times))
    return result
