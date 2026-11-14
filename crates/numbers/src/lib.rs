//! CPython 3.14 number behavior that results depend on. Each function equals
//! the Python call in its comment bit for bit; fixtures/numbers/ proves it.
//!
//! Inputs are what the Python product passes. Where Python would raise (an
//! empty list, a non-finite value for the exact statistics), the function
//! states the precondition instead of checking it.

use num_bigint::{BigInt, BigUint};

/// Built-in `sum(values)` over floats.
///
/// Python starts at the integer 0, so `sum([-0.0])` is `0.0`, and adds with
/// Neumaier compensation (CPython 3.12 and later). The compensation is added
/// once at the end, and only when it is finite and not zero. An empty slice
/// gives `0.0` where Python gives the integer 0.
pub fn sum(values: &[f64]) -> f64 {
    let mut total = 0.0;
    let mut compensation = 0.0;
    for &x in values {
        let t = total + x;
        if f64::abs(total) >= x.abs() {
            compensation += (total - t) + x;
        } else {
            compensation += (x - t) + total;
        }
        total = t;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total += compensation;
    }
    total
}

/// The product's equally weighted return of holdings
/// (`portfolio_results.mean_return`): `sum(values) / len(values)`, or `0.0`
/// for no values.
pub fn mean_return(values: &[f64]) -> f64 {
    if values.is_empty() { 0.0 } else { sum(values) / values.len() as f64 }
}

/// `statistics.mean(values)`: the exact sum divided by the count, as a
/// fraction, rounded once to the nearest float. An exact zero is `0.0`.
///
/// Precondition: `values` is not empty and every value is finite.
pub fn mean(values: &[f64]) -> f64 {
    let (integers, exponent) = integers(values);
    let total: BigInt = integers.iter().sum();
    let count = BigUint::from(values.len());
    let magnitude = scaled(total.magnitude().clone(), count, exponent);
    if total.sign() == num_bigint::Sign::Minus {
        -magnitude
    } else {
        magnitude
    }
}

/// `statistics.median(values)`: the middle member of the stably sorted
/// values, or `(low + high) / 2` of the two middle members.
///
/// Sorting keeps the order of equal members, so `-0.0` and `0.0` stay as
/// given. Precondition: `values` is not empty and holds no NaN.
pub fn median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let middle = sorted.len() / 2;
    if sorted.len() % 2 == 1 {
        sorted[middle]
    } else {
        (sorted[middle - 1] + sorted[middle]) / 2.0
    }
}

/// `statistics.pstdev(values)`: the population standard deviation.
///
/// The mean square deviation `(n * sum(x * x) - sum(x) ** 2) / n ** 2` is an
/// exact fraction; its square root is correctly rounded by the same steps as
/// CPython's `statistics._float_sqrt_of_frac`.
///
/// Precondition: `values` is not empty and every value is finite.
pub fn pstdev(values: &[f64]) -> f64 {
    let (integers, exponent) = integers(values);
    let count = BigInt::from(values.len());
    let total: BigInt = integers.iter().sum();
    let squares: BigInt = integers.iter().map(|x| x * x).sum();
    let deviations = (&count * squares - &total * &total).into_parts().1;
    let count = count.into_parts().1;
    let mut numerator = deviations;
    let mut denominator = &count * &count;
    if exponent >= 0 {
        numerator <<= 2 * exponent as u64;
    } else {
        denominator <<= 2 * exponent.unsigned_abs();
    }
    // Round to odd with at least 2 * 53 + 3 bits, then round once to a float.
    let q = (numerator.bits() as i64 - denominator.bits() as i64 - 109).div_euclid(2);
    if q >= 0 {
        let root = odd_root(&numerator, &(denominator << (2 * q) as u64)) << q as u64;
        divide(&root, &BigUint::from(1u8))
    } else {
        let root = odd_root(&(numerator << (-2 * q) as u64), &denominator);
        divide(&root, &(BigUint::from(1u8) << (-q) as u64))
    }
}

/// `min(values)`: a later member replaces the current one only when it is
/// smaller, so the first of equal members (`0.0` or `-0.0`) wins.
///
/// Precondition: `values` is not empty.
pub fn min(values: &[f64]) -> f64 {
    let mut least = values[0];
    for &x in &values[1..] {
        if x < least {
            least = x;
        }
    }
    least
}

/// `max(values)`: the first of equal members wins, as in [`min`].
///
/// Precondition: `values` is not empty.
pub fn max(values: &[f64]) -> f64 {
    let mut most = values[0];
    for &x in &values[1..] {
        if x > most {
            most = x;
        }
    }
    most
}

/// The trial-statistics percentile: linear interpolation between adjacent
/// ordered members (R type 7), `low + (high - low) * (position - left)` with
/// `position = (len - 1) * p`.
///
/// Precondition: `sorted` is not empty and is in the order of Python's
/// `sorted()`, a stable ascending sort: `sort_by(|a, b| a.partial_cmp(b).unwrap())`.
/// `p` is in `[0, 1]`.
pub fn percentile(sorted: &[f64], p: f64) -> f64 {
    let position = (sorted.len() - 1) as f64 * p;
    let left = position.floor();
    let low = sorted[left as usize];
    let high = sorted[position.ceil() as usize];
    low + (high - low) * (position - left)
}

/// `x ** y` for floats, where Python returns a float.
///
/// Precondition: no overflow, no zero to a negative power (Python raises on
/// both) and no negative base with a fractional power (Python returns a
/// complex number). In the other cases Python's special cases agree with the
/// C library's `pow`, which it then calls, and `f64::powf` calls the same C
/// library function.
pub fn pow(x: f64, y: f64) -> f64 {
    x.powf(y)
}

/// A float written to a SQLite REAL column and read back: NaN is stored as
/// NULL (`None`), and `-0.0` comes back as `0.0`. Other values are unchanged.
pub fn stored_real(x: f64) -> Option<f64> {
    if x.is_nan() {
        None
    } else if x == 0.0 {
        Some(0.0)
    } else {
        Some(x)
    }
}

/// A stored lane value in canonical units:
/// `float(Decimal(str(stored)).scaleb(scale))`, or `float(stored)` when
/// `scale` is 0, and `None` when the value or the result is not finite.
///
/// `str()` gives the decimal digits of `repr`. Moving their decimal exponent is
/// exact (the default context keeps 28 digits), and reading the text back
/// rounds correctly in both languages, so tiny results become `0.0` and the
/// sign of `-0.0` is kept.
pub fn canonical(stored: f64, scale: i32) -> Option<f64> {
    if !stored.is_finite() {
        return None;
    }
    let value = if scale == 0 {
        stored
    } else {
        let (digits, exponent) = repr(stored);
        format!("{digits}e{}", exponent + scale).parse().unwrap()
    };
    value.is_finite().then_some(value)
}

/// `repr(x)` of a finite float as signed integer digits and a decimal
/// exponent: the shortest decimal that reads back to `x`, and of those the
/// closest to `x`.
///
/// Rust's `{:e}` gives the same digits except when `x` lies exactly halfway
/// between two such decimals: Python then takes the even last digit, Rust
/// the upper one. For example `repr(973012718181.53125)` ends in `5312`, where
/// `{:e}` ends in `5313`. Rounding `x` to that many digits is not a fix: at a
/// power of two the nearest decimal can fall below the narrower rounding
/// interval there (`2.0f64.powi(-1017)` is `7.120236347223045e-307`, not
/// `...044`).
fn repr(x: f64) -> (String, i32) {
    let text = format!("{x:e}");
    let (mantissa, exponent) = text.split_once('e').unwrap();
    let digits = mantissa.replace('.', "");
    let count = digits.trim_start_matches('-').len();
    let exponent = exponent.parse::<i32>().unwrap() - (count as i32 - 1);
    // An exact tie needs 16 or more digits: with fewer, the neighbours of the
    // shortest decimal are too far apart to read back to `x`.
    let last: u64 = digits.trim_start_matches('-').parse().unwrap();
    if count >= 16 && last % 2 == 1 {
        let sign = if x < 0.0 { "-" } else { "" };
        for even in [last - 1, last + 1] {
            // The point halfway between `last` and `even`, times 10 ** exponent.
            let half = (last + even) * 5;
            if format!("{sign}{half}e{}", exponent - 1).parse() == Ok(x)
                && is_exact(x, half, exponent - 1)
                && format!("{sign}{even}e{exponent}").parse() == Ok(x)
            {
                return (format!("{sign}{even}"), exponent);
            }
        }
    }
    (digits, exponent)
}

/// Whether `|x|` equals `digits * 10 ** exponent` exactly.
fn is_exact(x: f64, digits: u64, exponent: i32) -> bool {
    let (integers, binary) = integers(&[x.abs()]);
    // |x| = integer * 2 ** binary; compare integer * 2 ** binary * 10 ** -exponent
    // with digits, moving negative powers to the other side.
    let mut left = integers[0].magnitude().clone();
    let mut right = BigUint::from(digits);
    let (twos, fives) = (binary - exponent as i64, -(exponent as i64));
    if twos >= 0 { left <<= twos as u64 } else { right <<= twos.unsigned_abs() }
    let power = BigUint::from(5u8).pow(fives.unsigned_abs() as u32);
    if fives >= 0 { left *= power } else { right *= power }
    left == right
}

/// `random.Random(seed)`: the Mersenne Twister of CPython's `random` module.
pub struct Random {
    state: [u32; N],
    index: usize,
}

const N: usize = 624;
const M: usize = 397;

impl Random {
    /// `random.Random(seed)` for an integer seed. The seed is one 32-bit
    /// word of the key that `init_by_array` takes.
    pub fn new(seed: u32) -> Random {
        let mut state = [0u32; N];
        state[0] = 19650218;
        for i in 1..N {
            let previous = state[i - 1];
            state[i] = 1812433253u32
                .wrapping_mul(previous ^ (previous >> 30))
                .wrapping_add(i as u32);
        }
        let key = [seed];
        let (mut i, mut j) = (1, 0);
        for _ in 0..N.max(key.len()) {
            let previous = state[i - 1];
            state[i] = (state[i] ^ (previous ^ (previous >> 30)).wrapping_mul(1664525))
                .wrapping_add(key[j])
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                state[0] = state[N - 1];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
        }
        for _ in 0..N - 1 {
            let previous = state[i - 1];
            state[i] = (state[i] ^ (previous ^ (previous >> 30)).wrapping_mul(1566083941))
                .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                state[0] = state[N - 1];
                i = 1;
            }
        }
        state[0] = 0x8000_0000;
        Random { state, index: N }
    }

    /// The index that `choice(seq)` draws from a sequence of length `len`:
    /// `_randbelow(len)`, which draws `getrandbits(len.bit_length())` until
    /// the draw is below `len`. A length of 1 still consumes draws.
    ///
    /// Precondition: `1 <= len < 2 ** 32`.
    pub fn choice(&mut self, len: usize) -> usize {
        let bits = usize::BITS - len.leading_zeros();
        loop {
            let draw = (self.next_u32() >> (32 - bits)) as usize;
            if draw < len {
                return draw;
            }
        }
    }

    fn next_u32(&mut self) -> u32 {
        if self.index >= N {
            let twist = |upper: u32, lower: u32, far: u32| {
                let y = (upper & 0x8000_0000) | (lower & 0x7fff_ffff);
                far ^ (y >> 1) ^ if y & 1 == 1 { 0x9908_b0df } else { 0 }
            };
            for k in 0..N {
                self.state[k] = twist(self.state[k], self.state[(k + 1) % N], self.state[(k + M) % N]);
            }
            self.index = 0;
        }
        let mut y = self.state[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^ (y >> 18)
    }
}

/// Finite floats as integers times `2 ** exponent`, all at the smallest
/// exponent among them, so that sums and squares are exact.
fn integers(values: &[f64]) -> (Vec<BigInt>, i64) {
    let parts: Vec<(i64, i64)> = values
        .iter()
        .map(|x| {
            let bits = x.to_bits();
            let field = ((bits >> 52) & 0x7ff) as i64;
            let fraction = (bits & ((1 << 52) - 1)) as i64;
            let (significand, exponent) = if field == 0 {
                (fraction, -1074)
            } else {
                (fraction | 1 << 52, field - 1075)
            };
            (if x.is_sign_negative() { -significand } else { significand }, exponent)
        })
        .collect();
    let exponent = parts.iter().map(|&(_, e)| e).min().unwrap();
    let integers = parts.iter().map(|&(s, e)| BigInt::from(s) << (e - exponent) as u64).collect();
    (integers, exponent)
}

/// `numerator * 2 ** exponent / denominator`, correctly rounded.
fn scaled(numerator: BigUint, denominator: BigUint, exponent: i64) -> f64 {
    if exponent >= 0 {
        divide(&(numerator << exponent as u64), &denominator)
    } else {
        divide(&numerator, &(denominator << exponent.unsigned_abs()))
    }
}

/// `isqrt(n // m) | (a * a * m != n)`: the square root of `n / m` as an
/// integer, rounded to odd.
fn odd_root(n: &BigUint, m: &BigUint) -> BigUint {
    let root = (n / m).sqrt();
    if &root * &root * m == *n { root } else { root | BigUint::from(1u8) }
}

/// Python's `int / int` for a positive denominator: the quotient rounded to
/// the nearest float, ties to even, subnormal results included. The result
/// must not overflow.
fn divide(numerator: &BigUint, denominator: &BigUint) -> f64 {
    if numerator.bits() == 0 {
        return 0.0;
    }
    // The quotient lies in [2 ** (k - 1), 2 ** (k + 1)). Take it in units of
    // 2 ** low, at least two bits finer than the result's last bit.
    let k = numerator.bits() as i64 - denominator.bits() as i64;
    let low = (k - 55).max(-1076);
    let (n, d) = if low < 0 {
        (numerator << low.unsigned_abs(), denominator.clone())
    } else {
        (numerator.clone(), denominator << low as u64)
    };
    let quotient = &n / &d;
    let inexact = &quotient * &d != n;
    let quotient = quotient.iter_u64_digits().next().unwrap_or(0);
    let width = (u64::BITS - quotient.leading_zeros()) as i64;
    // The exponent of the result's last bit: 53 significant bits, or fewer
    // below the normal range.
    let last = (width - 53 + low).max(-1074);
    let drop = (last - low) as u32;
    let mut significand = quotient >> drop;
    let rest = quotient & ((1 << drop) - 1);
    let half = 1 << (drop - 1);
    if rest > half || rest == half && (inexact || significand & 1 == 1) {
        significand += 1;
    }
    // A significand of 2 ** 53 after rounding carries into the exponent field.
    f64::from_bits(((last + 1074) as u64) * (1 << 52) + significand)
}
