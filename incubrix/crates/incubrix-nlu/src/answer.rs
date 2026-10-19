//! Reading the user's reply to a question: "the second one", "2", "all",
//! "the one at 2:15", "no", or the option's own words.

/// What the reply chose.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Pick {
    /// The option at this index.
    Option(usize),
    /// "never mind": nothing changes.
    Cancel,
    /// Could not tell.
    Unclear,
}

fn is_meta(label: &str) -> bool {
    let l = label.to_lowercase();
    l.starts_with("all")
        || l.starts_with("none")
        || l.starts_with("cancel")
        || l.starts_with("both")
}

fn ordinal(w: &str) -> Option<usize> {
    Some(match w {
        "first" | "1st" | "one" => 1,
        "second" | "2nd" | "two" => 2,
        "third" | "3rd" | "three" => 3,
        "fourth" | "4th" | "four" => 4,
        "fifth" | "5th" | "five" => 5,
        "sixth" | "6th" | "six" => 6,
        _ => return None,
    })
}

/// Matches `reply` to one of `options`.
pub fn pick(reply: &str, options: &[String]) -> Pick {
    let r = reply
        .trim()
        .trim_end_matches(['.', '!', '?'])
        .trim()
        .to_lowercase();
    if r.is_empty() {
        return Pick::Unclear;
    }
    if let Some(i) = options.iter().position(|o| o.to_lowercase() == r) {
        return Pick::Option(i);
    }
    let words: Vec<&str> = r
        .split(|c: char| !c.is_alphanumeric() && c != ':' && c != '.')
        .filter(|w| !w.is_empty())
        .collect();
    let has = |w: &str| words.contains(&w);
    let starts = |prefix: &str| {
        options
            .iter()
            .position(|o| o.to_lowercase().starts_with(prefix))
    };

    if has("yes") || has("yeah") || has("yep") || has("sure") || r == "ok" || r == "okay" {
        if let Some(i) = starts("yes") {
            return Pick::Option(i);
        }
    }
    if r == "no" || r.starts_with("no,") || r.starts_with("no ") || has("nope") {
        return starts("no").map(Pick::Option).unwrap_or(Pick::Cancel);
    }
    if ["none", "cancel", "neither", "nothing", "stop", "nevermind"]
        .iter()
        .any(|w| has(w))
        || r.contains("never mind")
        || r.contains("forget it")
    {
        return starts("none")
            .or(starts("cancel"))
            .map(Pick::Option)
            .unwrap_or(Pick::Cancel);
    }
    if has("all") || has("every") || has("everything") || has("both") || has("each") {
        if let Some(i) = starts("all").or(starts("both")) {
            return Pick::Option(i);
        }
    }
    // Options that are choices of occurrence, not "all"/"none".
    let plain: Vec<usize> = (0..options.len())
        .filter(|i| !is_meta(&options[*i]))
        .collect();
    // A time: "the one at 2:15".
    if let Some(t) = words.iter().find(|w| w.contains(':')) {
        let hits: Vec<usize> = (0..options.len())
            .filter(|i| options[*i].contains(t))
            .collect();
        if hits.len() == 1 {
            return Pick::Option(hits[0]);
        }
    }
    if has("last") || has("latest") || has("final") {
        if let Some(i) = plain.last() {
            return Pick::Option(*i);
        }
    }
    for (k, w) in words.iter().enumerate() {
        // "the one about teams" names an option by its words, not number 1.
        if *w == "one" && k > 0 && matches!(words[k - 1], "the" | "that" | "this" | "which") {
            continue;
        }
        if let Some(n) = ordinal(w).or_else(|| w.parse().ok()) {
            if n >= 1 {
                if let Some(i) = plain.get(n - 1) {
                    return Pick::Option(*i);
                }
                if n <= options.len() {
                    return Pick::Option(n - 1);
                }
            }
        }
    }
    if r.len() >= 3 {
        let hits: Vec<usize> = (0..options.len())
            .filter(|i| options[*i].to_lowercase().contains(&r))
            .collect();
        if hits.len() == 1 {
            return Pick::Option(hits[0]);
        }
    }
    Pick::Unclear
}

#[cfg(test)]
mod tests {
    use super::*;

    fn opts() -> Vec<String> {
        [
            "1:05 'our pricing is simple'",
            "2:15 'the pricing changed'",
            "3:15 'pricing for teams'",
            "All three",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect()
    }

    #[test]
    fn replies() {
        assert_eq!(pick("the second one", &opts()), Pick::Option(1));
        assert_eq!(pick("2", &opts()), Pick::Option(1));
        assert_eq!(pick("all of them", &opts()), Pick::Option(3));
        assert_eq!(pick("the last one", &opts()), Pick::Option(2));
        assert_eq!(pick("the one at 3:15", &opts()), Pick::Option(2));
        assert_eq!(pick("never mind", &opts()), Pick::Cancel);
        assert_eq!(pick("banana", &opts()), Pick::Unclear);
        assert_eq!(
            pick("the one about teams", &opts()),
            Pick::Unclear,
            "left to the model"
        );
        let yn = vec!["Yes, remove it".to_string(), "No, keep it".to_string()];
        assert_eq!(pick("yes", &yn), Pick::Option(0));
        assert_eq!(pick("no", &yn), Pick::Option(1));
    }
}
