pub struct Gate;

impl Gate {
    // 1 + if + && + match arms (Some, None) = 5; `_`-free match, `?` not counted
    pub fn check(&self, a: bool, b: Option<u8>) -> Result<u8, ()> {
        if a && b.is_some() {
            return Ok(1);
        }
        let v = match b {
            Some(x) => x,
            None => 0,
        };
        Ok(v)
    }

    // 1 + for + while + `let else` + closure `if` (inline) = 5; wildcard arm with no guard is free
    pub fn loops(&self, xs: &[u8]) -> u8 {
        let mut n = 0;
        for x in xs {
            while n < *x { n += 1; }
        }
        let Some(first) = xs.first() else { return 0 };
        let f = |y: u8| if y > 1 { y } else { 0 };
        match n { _ => f(*first) }
    }
}

// 1 + if + nested fn excluded = 2
fn outer(a: bool) -> u8 {
    fn inner(b: bool) -> u8 { if b { 1 } else { 0 } }
    if a { inner(a) } else { 0 }
}

#[cfg(test)]
mod tests {
    use super::*;
    // test helper inside cfg(test): CC 1
    fn helper() -> bool { true }
    #[test]
    fn checks() { assert!(outer(helper()) == 1); }
}

#[tokio::test]
async fn async_case() {}
