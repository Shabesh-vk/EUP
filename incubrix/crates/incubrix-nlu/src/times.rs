//! Times and numbers as people type them: "1:20", "80 seconds", "a minute
//! twenty", "one and a half minutes", "90s", "2m30s", "half a minute".
//! Results are integer milliseconds.

/// A number word or digits: "twenty five" -> 25, "2.5" -> 2.5 (in
/// thousandths, so no float leaves this module).
pub fn number_milli(s: &str) -> Option<i64> {
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    if let Some(v) = decimal_milli(s) {
        return Some(v);
    }
    let mut total = 0i64;
    let mut any = false;
    for w in s.split([' ', '-']).filter(|w| !w.is_empty()) {
        let v = match w {
            "a" | "an" | "one" => 1,
            "zero" => 0,
            "two" => 2,
            "three" => 3,
            "four" => 4,
            "five" => 5,
            "six" => 6,
            "seven" => 7,
            "eight" => 8,
            "nine" => 9,
            "ten" => 10,
            "eleven" => 11,
            "twelve" => 12,
            "thirteen" => 13,
            "fourteen" => 14,
            "fifteen" => 15,
            "sixteen" => 16,
            "seventeen" => 17,
            "eighteen" => 18,
            "nineteen" => 19,
            "twenty" => 20,
            "thirty" => 30,
            "forty" => 40,
            "fifty" => 50,
            "sixty" => 60,
            "seventy" => 70,
            "eighty" => 80,
            "ninety" => 90,
            "hundred" => {
                total = total.max(1) * 100;
                any = true;
                continue;
            }
            "and" => continue,
            _ => return None,
        };
        total += v;
        any = true;
    }
    any.then_some(total * 1000)
}

/// "2.5" -> 2500, "10" -> 10000.
fn decimal_milli(s: &str) -> Option<i64> {
    let (int, frac) = s.split_once('.').unwrap_or((s, ""));
    if int.is_empty() && frac.is_empty() {
        return None;
    }
    if !int.chars().all(|c| c.is_ascii_digit()) || !frac.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let whole: i64 = if int.is_empty() { 0 } else { int.parse().ok()? };
    let mut milli = 0;
    for (i, c) in frac.chars().take(3).enumerate() {
        milli += (c as i64 - '0' as i64) * 10i64.pow(2 - i as u32);
    }
    Some(whole * 1000 + milli)
}

fn unit_ms(u: &str) -> Option<i64> {
    match u {
        "s" | "sec" | "secs" | "second" | "seconds" => Some(1000),
        "m" | "min" | "mins" | "minute" | "minutes" => Some(60_000),
        "h" | "hr" | "hrs" | "hour" | "hours" => Some(3_600_000),
        _ => None,
    }
}

/// A time or a length, the whole string: "1:20", "1:02:03", "80 seconds",
/// "a minute twenty", "a minute and a half", "half a minute", "90s",
/// "2m30s", "1 minute 20 seconds", "0:12.5".
pub fn parse_time(s: &str) -> Option<i64> {
    let s = s
        .trim()
        .trim_start_matches("the ")
        .trim_end_matches(['.', ',', '?', '!'])
        .trim();
    if s.is_empty() {
        return None;
    }
    // Clock: m:ss, h:mm:ss, with optional fraction.
    if s.contains(':') {
        let parts: Vec<&str> = s.split(':').collect();
        if parts.len() > 3 || parts.iter().any(|p| p.is_empty()) {
            return None;
        }
        let mut ms = 0i64;
        for (i, p) in parts.iter().enumerate() {
            let last = i + 1 == parts.len();
            let v = if last {
                decimal_milli(p)?
            } else {
                p.parse::<i64>().ok()? * 1000
            };
            ms = ms * 60 + v;
        }
        return Some(ms);
    }
    // "half a minute", "a minute and a half", "one and a half minutes".
    if let Some(rest) = s
        .strip_prefix("half a ")
        .or(s.strip_prefix("half an "))
        .or(s.strip_prefix("half "))
    {
        return unit_ms(rest).map(|u| u / 2);
    }
    // "a minute and a half": the unit before, plus half of it.
    if let Some(rest) = s.strip_suffix(" and a half") {
        let base = parse_time(rest)?;
        let unit = rest.split_whitespace().last().and_then(unit_ms)?;
        return Some(base + unit / 2);
    }
    // "one and a half minutes".
    if let Some((n, unit)) = s.split_once(" and a half ") {
        return Some((number_milli(n)? + 500) * unit_ms(unit.trim())? / 1000);
    }
    let s = s.to_owned();
    // Compact forms: "90s", "2m30s", "1h5m".
    if s.chars().all(|c| c.is_ascii_alphanumeric() || c == '.')
        && s.chars().next()?.is_ascii_digit()
    {
        let mut total = 0i64;
        let mut num = String::new();
        let mut unit = String::new();
        let mut any = false;
        for c in s.chars().chain(std::iter::once(' ')) {
            if c.is_ascii_digit() || c == '.' {
                if !unit.is_empty() {
                    total += decimal_milli(&num)? * unit_ms(&unit)? / 1000;
                    num.clear();
                    unit.clear();
                    any = true;
                }
                num.push(c);
            } else if c.is_ascii_alphabetic() {
                unit.push(c);
            } else if !num.is_empty() {
                let u = if unit.is_empty() {
                    1000
                } else {
                    unit_ms(&unit)?
                };
                total += decimal_milli(&num)? * u / 1000;
                any = true;
            }
        }
        if any {
            return Some(total);
        }
    }
    // Words: "<number> <unit> [and] [<number> [<unit>]]".
    let words: Vec<&str> = s.split_whitespace().filter(|w| *w != "and").collect();
    let mut total = 0i64;
    let mut num: Vec<&str> = Vec::new();
    let mut last_unit: Option<i64> = None;
    let mut any = false;
    for w in &words {
        if let Some(u) = unit_ms(w) {
            let n = if num.is_empty() {
                1000
            } else {
                number_milli(&num.join(" "))?
            };
            total += n * u / 1000;
            num.clear();
            last_unit = Some(u);
            any = true;
        } else {
            num.push(w);
        }
    }
    if !num.is_empty() {
        // A bare trailing number: "a minute twenty" means 20 of the next unit down.
        let n = number_milli(&num.join(" "))?;
        let u = match last_unit {
            Some(60_000) => 1000,
            Some(3_600_000) => 60_000,
            Some(_) => return None,
            None => 1000,
        };
        total += n * u / 1000;
        any = true;
    }
    any.then_some(total)
}

/// The times said in a sentence, longest match first: ("half a minute",
/// 30000), ("1:20", 80000). Only phrases with a unit or a clock count, so a
/// bare "one" or "a" is never read as a time. Given to language models,
/// which are unreliable at this arithmetic.
pub fn mentions(text: &str) -> Vec<(String, i64)> {
    let words: Vec<String> = text
        .to_lowercase()
        .split(|c: char| c.is_whitespace() || c == ',' || c == '?' || c == '!')
        .map(|w| {
            w.trim_matches(|c: char| !c.is_alphanumeric() && c != ':' && c != '.')
                .trim_end_matches('.')
                .to_owned()
        })
        .filter(|w| !w.is_empty())
        .collect();
    let timey = |p: &str| {
        p.contains(':')
            || p.split_whitespace().any(|w| unit_ms(w).is_some())
            || (p.chars().next().is_some_and(|c| c.is_ascii_digit())
                && p.chars()
                    .last()
                    .is_some_and(|c| matches!(c, 's' | 'm' | 'h')))
    };
    let mut out = Vec::new();
    let mut i = 0;
    while i < words.len() {
        let mut hit = None;
        for len in (1..=6).rev() {
            if i + len > words.len() {
                continue;
            }
            let phrase = words[i..i + len].join(" ");
            if !timey(&phrase) {
                continue;
            }
            if let Some(ms) = parse_time(&phrase) {
                hit = Some((len, phrase, ms));
                break;
            }
        }
        match hit {
            Some((len, phrase, ms)) => {
                out.push((phrase, ms));
                i += len;
            }
            None => i += 1,
        }
    }
    out
}

/// A speed: "2x", "2 times", "twice", "double", "half speed", "1.5x",
/// "50%" (as a change: +50 % -> 1.5x). Thousandths.
pub fn parse_speed(s: &str) -> Option<u32> {
    let s = s.trim();
    let v = if let Some(n) = s.strip_suffix('x').or(s.strip_suffix(" x")) {
        number_milli(n.trim())?
    } else if let Some(n) = s
        .strip_suffix(" times faster")
        .or(s.strip_suffix(" times as fast"))
        .or(s.strip_suffix(" times"))
    {
        number_milli(n.trim())?
    } else if let Some(n) = s.strip_suffix('%') {
        1000 + number_milli(n.trim())? / 100
    } else {
        match s {
            "twice" | "twice as fast" | "double" | "double speed" => 2000,
            "half speed" | "half" => 500,
            "triple" | "three times" => 3000,
            _ => number_milli(s)?,
        }
    };
    u32::try_from(v).ok().filter(|v| *v > 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_brief_s_time_forms() {
        assert_eq!(parse_time("80 seconds"), Some(80_000));
        assert_eq!(parse_time("a minute twenty"), Some(80_000));
        assert_eq!(parse_time("1:20"), Some(80_000));
        assert_eq!(parse_time("1 minute 20 seconds"), Some(80_000));
        assert_eq!(parse_time("one minute and twenty seconds"), Some(80_000));
        assert_eq!(parse_time("90s"), Some(90_000));
        assert_eq!(parse_time("2m30s"), Some(150_000));
        assert_eq!(parse_time("half a minute"), Some(30_000));
        assert_eq!(parse_time("half minute"), Some(30_000));
        assert_eq!(parse_time("a minute and a half"), Some(90_000));
        assert_eq!(parse_time("1:02:03"), Some(3_723_000));
        assert_eq!(parse_time("0:12.5"), Some(12_500));
        assert_eq!(parse_time("30"), Some(30_000));
        assert_eq!(parse_time("ten seconds"), Some(10_000));
        assert_eq!(parse_time("twenty five seconds"), Some(25_000));
        assert_eq!(parse_time("the pricing"), None);
    }

    #[test]
    fn times_in_a_sentence() {
        assert_eq!(
            mentions("could you trim off the opening half minute? it drags"),
            vec![("half minute".to_owned(), 30_000)]
        );
        assert_eq!(
            mentions("play the bit from one minute to a minute thirty at double speed"),
            vec![
                ("one minute".to_owned(), 60_000),
                ("a minute thirty".to_owned(), 90_000)
            ]
        );
        assert_eq!(
            mentions("cut 0:30 to 0:40"),
            vec![("0:30".to_owned(), 30_000), ("0:40".to_owned(), 40_000)]
        );
        assert!(mentions("bring the intro back").is_empty());
    }

    #[test]
    fn speeds() {
        assert_eq!(parse_speed("2x"), Some(2000));
        assert_eq!(parse_speed("1.5x"), Some(1500));
        assert_eq!(parse_speed("10x"), Some(10_000));
        assert_eq!(parse_speed("twice"), Some(2000));
        assert_eq!(parse_speed("3 times"), Some(3000));
        assert_eq!(parse_speed("50%"), Some(1500));
    }
}
