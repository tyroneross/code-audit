//! Parser-backed per-function cyclomatic complexity (CC) and structural
//! duplicate leads for Rust, TypeScript/TSX, Java, Go and Swift.
//!
//! The analyzer reads the named source files and parses them with pinned
//! tree-sitter grammars. It never builds, imports or runs the measured
//! project. Output is JSON on stdout; `complexity.py` merges it with its
//! Python rows so every language shares one report schema.
//!
//! Counting rules (each adds 1 to a function that starts at 1):
//! - Rust: `if`/`if let`, `while`/`while let`, `for`, `let ... else`, every
//!   match arm except the default arm (a bare `_` or a single lowercase
//!   binding such as `other =>`, without a guard), each `&&`/`||`, including
//!   the `&&` joining a let chain (`if let Some(v) = o && v > 3`).
//!   `loop` (no condition) and `?` are not counted.
//! - TypeScript: `if`, `for`, `for in/of`, `while`, `do`, `?:`, `catch`, each
//!   non-default `case`, each `&&`/`||`/`??`. Optional chaining is not counted.
//! - Java: `if`, `for`, enhanced `for`, `while`, `do`, `?:`, `catch`, each
//!   switch label except `default` and `case null, default`, pattern guards,
//!   each `&&`/`||`. A multi-value label (`case 1, 2 ->`) counts once.
//! - Go: `if`, `for`, each non-default `case` in expression, type and select
//!   switches, each `&&`/`||`.
//! - Swift: `if`, `guard`, `for`, `while`, `repeat`, `?:`, `catch`, each
//!   non-default `case` plus 1 for its `where` guard, each `&&`/`||`/`??`. An
//!   `if`/`guard`/`while` counts once per comma-separated clause, so
//!   `if let x, let y, x > y` adds 3 and `if case .some(let v) = x` adds 1.
//!
//! Named functions are measured separately and do not add to an enclosing
//! function. Swift computed properties are rows named after the property
//! (`V.body`), or one row per accessor (`V.label.get`, `.set`, `.modify`,
//! `.willSet`, `.didSet`). Anonymous closures, lambdas, arrow functions and
//! function literals add their decisions to the enclosing function, because in
//! these languages they routinely carry control flow inline. An arrow
//! function or function expression bound to a variable or class field is
//! treated as a named function. An anonymous function with no enclosing
//! function (a top-level callback, `export default () => {}`, a Go
//! package-level `func` literal, a Java field lambda, `static {}` or instance
//! initializer, a Rust closure in a `static`) gets its own row named
//! `<anonymous@LINE>`, qualified by scope. TypeScript callbacks passed to
//! `describe`/`it`/`test` and their hooks always get their own row and are
//! test code. Decisions that still have no function (top-level statements,
//! field or constant initializers) are counted per file as
//! `unowned_decisions`; `complexity.py` reports them as a gap.
//!
//! Structural signals per function row (method `tree-sitter-structure-v1`):
//! - `max_nesting`: deepest level of nested control flow. Conditionals, loops,
//!   `match`/`switch`, `catch`, conditional expressions and anonymous functions
//!   that add to the row each open one level. An `else if` continues its chain
//!   at the same level; a conditional expression inside another opens a new one,
//!   so a chained ternary reads as nested. Swift `guard` and Rust `let ... else`
//!   are early exits and open no level.
//! - `bumps`: top-level control-flow blocks in the function that themselves
//!   contain nested control flow (each is a separate chunk of nested logic).
//! - `condition_operators`: the most `&&`/`||` operators combined in one
//!   expression (Rust let-chain joins included). Counting restarts at every
//!   statement, block, argument list and nested control-flow construct.
//! - `params`: declared parameters, without a Rust `self` or Java receiver. A Go
//!   declaration `a, b int` counts 2.
//!
//! Pattern leads per file (`patterns`), each compared as source text with
//! whitespace removed and reported only when no operand calls a function,
//! awaits, allocates or mutates:
//! - `identical_operands`: comparisons, `&&`, `||`, `-`, `/` and `%` whose two
//!   sides are the same expression, so the result is fixed. Bitwise `&`, `|` and
//!   `^` are left out (`x & x` coerces to a 32-bit integer in JavaScript). An
//!   equality test is skipped when its line names a float, NaN or infinity, the
//!   usual NaN check. Not run for Swift, whose grammar does not preserve
//!   precedence in mixed expressions, nor when the right side is followed by
//!   `!`, `.`, `(` or `[`: the grammar then split a longer expression
//!   (TypeScript `a !== a!.trim()`).
//! - `self_assignment`: `x = x` with the plain assignment operator.
//! - `duplicate_branches`: an `if`/`else` or conditional expression whose two
//!   branches are the same code. Skipped when the condition binds a name
//!   (`if let`, `if case`, `instanceof` pattern): the same text then reads
//!   different variables in each branch.
//! - `repeated_condition`: a condition that repeats an earlier one in the same
//!   `else if` chain, so its branch cannot run.

use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::path::{Component, Path, PathBuf};
use tree_sitter::{Node, Parser};

const LOCKFILE: &str = include_str!("../Cargo.lock");
const SHINGLE: usize = 5;
/// Upper bound on MinHash functions; banding is derived from the threshold.
const MAX_MINHASHES: usize = 128;
/// Target probability that a pair exactly at the threshold becomes a candidate.
const TARGET_RECALL: f64 = 0.98;
/// TypeScript test-framework calls whose callbacks are test code (Jest, Vitest, Mocha).
const TEST_CALLEES: [&str; 7] = ["describe", "it", "test", "beforeEach", "afterEach", "beforeAll", "afterAll"];
/// Operators whose result is fixed when both operands are the same expression.
const FIXED_WHEN_IDENTICAL: [&str; 13] = ["==", "!=", "===", "!==", "<", ">", "<=", ">=", "&&", "||", "-", "/", "%"];
/// Words that mark a line as float handling, where `x != x` is the usual NaN test.
const FLOAT_WORDS: [&str; 6] = ["nan", "float", "inf", "f32", "f64", "double"];
/// Node-kind fragments that mark an expression with an effect or a fresh value.
const IMPURE_KINDS: [&str; 10] = ["call", "invocation", "await", "update", "creation", "new_expression", "yield", "try", "closure", "lambda"];
/// Node-kind fragments where a new statement, block or argument list starts.
const CONDITION_BOUNDARIES: [&str; 9] = ["block", "statements", "statement_list", "body", "argument", "arm", "case", "entry", "declaration"];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Lang {
    Rust,
    TypeScript,
    Tsx,
    Java,
    Go,
    Swift,
}

impl Lang {
    fn from_path(path: &str) -> Option<Lang> {
        let ext = Path::new(path).extension()?.to_str()?;
        Some(match ext {
            "rs" => Lang::Rust,
            "ts" | "mts" | "cts" => Lang::TypeScript,
            "tsx" => Lang::Tsx,
            "java" => Lang::Java,
            "go" => Lang::Go,
            "swift" => Lang::Swift,
            _ => return None,
        })
    }

    fn name(self) -> &'static str {
        match self {
            Lang::Rust => "rust",
            Lang::TypeScript | Lang::Tsx => "typescript",
            Lang::Java => "java",
            Lang::Go => "go",
            Lang::Swift => "swift",
        }
    }

    fn grammar_crate(self) -> &'static str {
        match self {
            Lang::Rust => "tree-sitter-rust",
            Lang::TypeScript | Lang::Tsx => "tree-sitter-typescript",
            Lang::Java => "tree-sitter-java",
            Lang::Go => "tree-sitter-go",
            Lang::Swift => "tree-sitter-swift",
        }
    }

    fn grammar(self) -> tree_sitter::Language {
        match self {
            Lang::Rust => tree_sitter_rust::LANGUAGE.into(),
            Lang::TypeScript => tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
            Lang::Tsx => tree_sitter_typescript::LANGUAGE_TSX.into(),
            Lang::Java => tree_sitter_java::LANGUAGE.into(),
            Lang::Go => tree_sitter_go::LANGUAGE.into(),
            Lang::Swift => tree_sitter_swift::LANGUAGE.into(),
        }
    }
}

/// Exact versions resolved in Cargo.lock, so reports name the parser that ran.
fn locked_versions() -> HashMap<&'static str, String> {
    let wanted = [
        "tree-sitter",
        "tree-sitter-rust",
        "tree-sitter-typescript",
        "tree-sitter-java",
        "tree-sitter-go",
        "tree-sitter-swift",
    ];
    let mut found = HashMap::new();
    let mut current: Option<&'static str> = None;
    for line in LOCKFILE.lines() {
        if let Some(name) = line.strip_prefix("name = \"").and_then(|s| s.strip_suffix('"')) {
            current = wanted.iter().copied().find(|w| *w == name);
        } else if let (Some(name), Some(v)) = (
            current,
            line.strip_prefix("version = \"").and_then(|s| s.strip_suffix('"')),
        ) {
            found.insert(name, v.to_string());
            current = None;
        }
    }
    found
}

struct Row {
    name: String,
    line: usize,
    end_line: usize,
    cc: u32,
    nodes: u32,
    test_reason: Option<String>,
    kinds: Vec<u16>,
    max_nesting: u32,
    /// Deepest level reached inside the top-level block being walked.
    chunk_depth: u32,
    bumps: u32,
    condition_operators: u32,
    params: u32,
}

struct Pattern {
    rule: &'static str,
    line: usize,
    row: Option<usize>,
    detail: String,
}

struct Walker<'a> {
    lang: Lang,
    src: &'a [u8],
    rows: Vec<Row>,
    scope: Vec<String>,
    /// Inline `mod` names enclosing the current node (Rust), for module file paths.
    mod_path: Vec<String>,
    /// Out-of-line `mod name;` declarations: (candidate files, declared under test).
    modules: Vec<(Vec<String>, bool)>,
    /// Rust: the file is a crate root (`lib.rs`, `main.rs`, `src/bin/*.rs`, ...),
    /// so its out-of-line modules live beside it.
    crate_root: bool,
    /// Decision points outside every measured function.
    unowned: u32,
    patterns: Vec<Pattern>,
    /// Running `&&`/`||` count of each expression that combines conditions.
    conditions: Vec<u32>,
}

fn text<'a>(node: Node, src: &'a [u8]) -> &'a str {
    node.utf8_text(src).unwrap_or("")
}

fn field_text<'a>(node: Node, field: &str, src: &'a [u8]) -> Option<&'a str> {
    node.child_by_field_name(field).map(|n| text(n, src))
}

/// Strip generic parameters and whitespace from a type name: `Foo<T>` -> `Foo`.
fn bare_type(raw: &str) -> String {
    let head = raw.split('<').next().unwrap_or(raw);
    head.split_whitespace().collect::<Vec<_>>().join("")
}

/// Source text with all whitespace removed, for comparing two fragments.
fn squeezed(node: Node, src: &[u8]) -> String {
    text(node, src).split_whitespace().collect()
}

/// False when the expression calls, awaits, allocates or mutates, so evaluating
/// it twice could differ.
fn pure(node: Node, src: &[u8]) -> bool {
    let kind = node.kind();
    if IMPURE_KINDS.iter().any(|k| kind.contains(k)) || (kind == "unary_expression" && text(node, src).starts_with("<-")) {
        return false;
    }
    let mut cursor = node.walk();
    let children: Vec<Node> = node.children(&mut cursor).collect();
    children.into_iter().all(|c| pure(c, src))
}

fn word_present(haystack: &str, word: &str) -> bool {
    haystack
        .split(|c: char| !(c.is_alphanumeric() || c == '_'))
        .any(|w| w == word)
}

/// Rust attribute path and arguments, from `#[path(args)]` or `#![...]`.
fn rust_attr(raw: &str) -> (String, String) {
    let inner = raw
        .trim()
        .trim_start_matches('#')
        .trim_start_matches('!')
        .trim()
        .trim_start_matches('[')
        .trim_end_matches(']');
    match inner.find('(') {
        Some(i) => (inner[..i].trim().to_string(), inner[i..].to_string()),
        None => (inner.trim().to_string(), String::new()),
    }
}

fn rust_attr_marks_test(path: &str) -> bool {
    matches!(path, "test" | "bench" | "rstest" | "test_case" | "quickcheck")
        || path.ends_with("::test")
        || path.ends_with("::test_case")
}

/// A `cfg` predicate: `test`, `unix`, `feature = "x"`, `all(..)`, `any(..)`, `not(..)`.
enum Cfg {
    Atom(bool),
    All(Vec<Cfg>),
    Any(Vec<Cfg>),
    Not(Box<Cfg>),
}

/// Split cfg arguments into identifiers, string literals and punctuation.
fn cfg_tokens(src: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut chars = src.chars().peekable();
    while let Some(c) = chars.next() {
        if c.is_whitespace() {
            continue;
        }
        if c == '"' {
            // String literals are opaque values; their contents never name `test`.
            let mut escaped = false;
            for d in chars.by_ref() {
                if !escaped && d == '"' {
                    break;
                }
                escaped = !escaped && d == '\\';
            }
            out.push("\"\"".into());
        } else if c.is_alphanumeric() || c == '_' || c == ':' {
            let mut word = c.to_string();
            while let Some(&d) = chars.peek() {
                if !(d.is_alphanumeric() || d == '_' || d == ':') {
                    break;
                }
                word.push(d);
                chars.next();
            }
            out.push(word);
        } else {
            out.push(c.to_string());
        }
    }
    out
}

fn cfg_parse(tokens: &[String], pos: &mut usize) -> Option<Cfg> {
    let head = tokens.get(*pos)?.clone();
    *pos += 1;
    match tokens.get(*pos).map(String::as_str) {
        Some("=") => {
            *pos += 2;
            Some(Cfg::Atom(false))
        }
        Some("(") => {
            *pos += 1;
            let mut items = Vec::new();
            while tokens.get(*pos).map(String::as_str) != Some(")") {
                items.push(cfg_parse(tokens, pos)?);
                if tokens.get(*pos).map(String::as_str) == Some(",") {
                    *pos += 1;
                }
            }
            *pos += 1;
            match head.as_str() {
                "all" => Some(Cfg::All(items)),
                "any" => Some(Cfg::Any(items)),
                "not" if items.len() == 1 => Some(Cfg::Not(Box::new(items.pop()?))),
                _ => None,
            }
        }
        _ => Some(Cfg::Atom(head == "test")),
    }
}

/// (can be true, can be false) when `test` is false and every other atom is free.
fn cfg_outcomes(cfg: &Cfg) -> (bool, bool) {
    match cfg {
        Cfg::Atom(true) => (false, true),
        Cfg::Atom(false) => (true, true),
        Cfg::All(xs) => (xs.iter().all(|x| cfg_outcomes(x).0), xs.iter().any(|x| cfg_outcomes(x).1)),
        Cfg::Any(xs) => (xs.iter().any(|x| cfg_outcomes(x).0), xs.iter().all(|x| cfg_outcomes(x).1)),
        Cfg::Not(x) => {
            let (t, f) = cfg_outcomes(x);
            (f, t)
        }
    }
}

/// True only when the `cfg(..)` predicate cannot hold without `test`, so the item
/// is compiled for tests alone: `test`, `all(test, unix)`, but not `any(test, x)`,
/// `not(any(test, miri))` or `feature = "test-util"`.
fn rust_attr_is_cfg_test(path: &str, args: &str) -> bool {
    if path != "cfg" {
        return false;
    }
    let tokens = cfg_tokens(args);
    if tokens.first().map(String::as_str) != Some("(") {
        return false;
    }
    let mut pos = 1;
    match cfg_parse(&tokens, &mut pos) {
        Some(cfg) if tokens.get(pos).map(String::as_str) == Some(")") => !cfg_outcomes(&cfg).0,
        _ => false,
    }
}

/// Attributes in tree-sitter-rust are preceding siblings of the item.
fn rust_preceding_attrs<'t>(node: Node<'t>, src: &[u8]) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut prev = node.prev_named_sibling();
    while let Some(p) = prev {
        match p.kind() {
            "attribute_item" => out.push(rust_attr(text(p, src))),
            "line_comment" | "block_comment" => {}
            _ => break,
        }
        prev = p.prev_named_sibling();
    }
    out
}

impl<'a> Walker<'a> {
    fn new(lang: Lang, src: &'a [u8], crate_root: bool) -> Self {
        Walker {
            lang,
            src,
            rows: Vec::new(),
            scope: Vec::new(),
            mod_path: Vec::new(),
            modules: Vec::new(),
            crate_root,
            unowned: 0,
            patterns: Vec::new(),
            conditions: Vec::new(),
        }
    }

    /// Returns (display name, name node) when `node` starts a named function.
    fn named_function(&self, node: Node<'a>) -> Option<(String, Node<'a>)> {
        let src = self.src;
        let named = |field: &str| node.child_by_field_name(field).map(|n| (text(n, src).to_string(), n));
        match (self.lang, node.kind()) {
            (Lang::Rust, "function_item") => named("name"),
            (Lang::TypeScript | Lang::Tsx, "function_declaration" | "generator_function_declaration" | "method_definition") => named("name"),
            (Lang::TypeScript | Lang::Tsx, "arrow_function" | "function_expression" | "generator_function") => {
                let parent = node.parent()?;
                match parent.kind() {
                    "variable_declarator" | "public_field_definition" => {
                        let n = parent.child_by_field_name("name")?;
                        Some((text(n, src).to_string(), n))
                    }
                    _ if node.kind() != "arrow_function" => named("name"),
                    _ => None,
                }
            }
            (Lang::Java, "method_declaration" | "constructor_declaration" | "compact_constructor_declaration") => named("name"),
            (Lang::Go, "function_declaration") => named("name"),
            (Lang::Go, "method_declaration") => {
                let (name, n) = named("name")?;
                let receiver = node.child_by_field_name("receiver").map(|r| go_receiver_type(r, src));
                Some((match receiver {
                    Some(r) if !r.is_empty() => format!("{r}.{name}"),
                    _ => name,
                }, n))
            }
            (Lang::Swift, "function_declaration") => named("name"),
            (Lang::Swift, "init_declaration") => Some(("init".into(), node)),
            (Lang::Swift, "deinit_declaration") => Some(("deinit".into(), node)),
            (Lang::Swift, "subscript_declaration") => Some(("subscript".into(), node)),
            (Lang::Swift, "computed_property") => {
                let mut cursor = node.walk();
                let has_accessors = node
                    .children(&mut cursor)
                    .any(|c| matches!(c.kind(), "computed_getter" | "computed_setter" | "computed_modify"));
                let n = swift_property_name(node.parent()?)?;
                (!has_accessors).then(|| (text(n, src).to_string(), n))
            }
            (Lang::Swift, "computed_getter" | "computed_setter" | "computed_modify" | "willset_clause" | "didset_clause") => {
                let n = swift_property_name(node.parent()?.parent()?)?;
                let accessor = match node.kind() {
                    "computed_getter" => "get",
                    "computed_setter" => "set",
                    "computed_modify" => "modify",
                    "willset_clause" => "willSet",
                    _ => "didSet",
                };
                Some((format!("{}.{accessor}", text(n, src)), node))
            }
            _ => None,
        }
    }

    /// Anonymous function-like nodes that become their own row when no function encloses them.
    fn anonymous_function(&self, node: Node) -> bool {
        matches!(
            (self.lang, node.kind()),
            (Lang::TypeScript | Lang::Tsx, "arrow_function" | "function_expression" | "generator_function")
                | (Lang::Go, "func_literal")
                | (Lang::Java, "lambda_expression" | "static_initializer")
                | (Lang::Rust, "closure_expression")
                | (Lang::Swift, "lambda_literal")
        ) || (self.lang == Lang::Java && node.kind() == "block" && node.parent().is_some_and(|p| p.kind() == "class_body"))
    }

    /// TypeScript callback passed directly to `describe`/`it`/`test` or a hook,
    /// including `.only`, `.skip` and `.each(...)` forms.
    fn ts_test_callback(&self, node: Node) -> bool {
        if !matches!(self.lang, Lang::TypeScript | Lang::Tsx) || !self.anonymous_function(node) {
            return false;
        }
        let Some(call) = node.parent().filter(|p| p.kind() == "arguments").and_then(|a| a.parent()) else { return false };
        let callee = field_text(call, "function", self.src).unwrap_or("");
        let head = callee.split(['.', '(', '`']).next().unwrap_or("").trim();
        TEST_CALLEES.contains(&head)
    }

    /// Row for a function-like node: named functions always, anonymous ones only
    /// when nothing encloses them or when they are test-framework callbacks.
    fn function_row(&self, node: Node<'a>, current: Option<usize>) -> Option<(String, Node<'a>)> {
        if let Some(named) = self.named_function(node) {
            return Some(named);
        }
        if !self.anonymous_function(node) || (current.is_some() && !self.ts_test_callback(node)) {
            return None;
        }
        let pos = node.start_position();
        let mut name = format!("<anonymous@{}>", pos.row + 1);
        let qualified = |n: &str| self.scope.iter().map(String::as_str).chain(std::iter::once(n)).collect::<Vec<_>>().join(".");
        let taken = qualified(&name);
        if self.rows.iter().any(|r| r.name == taken) {
            name = format!("<anonymous@{}:{}>", pos.row + 1, pos.column + 1);
        }
        Some((name, node))
    }

    /// Names that qualify functions declared inside this node.
    fn scope_name(&self, node: Node) -> Option<String> {
        let src = self.src;
        match (self.lang, node.kind()) {
            (Lang::Rust, "mod_item" | "trait_item") => field_text(node, "name", src).map(bare_type),
            (Lang::Rust, "impl_item") => field_text(node, "type", src).map(bare_type),
            (Lang::TypeScript | Lang::Tsx, "class_declaration" | "abstract_class_declaration" | "class" | "interface_declaration") => {
                field_text(node, "name", src).map(bare_type)
            }
            (Lang::Java, "class_declaration" | "interface_declaration" | "enum_declaration" | "record_declaration" | "annotation_type_declaration") => {
                field_text(node, "name", src).map(bare_type)
            }
            (Lang::Swift, "class_declaration" | "protocol_declaration") => field_text(node, "name", src).map(bare_type),
            _ => None,
        }
    }

    fn decision(&self, node: Node) -> u32 {
        let src = self.src;
        let op = || field_text(node, "operator", src).unwrap_or("");
        match (self.lang, node.kind()) {
            (Lang::Rust, "if_expression" | "while_expression" | "for_expression") => 1,
            (Lang::Rust, "let_declaration") => node.child_by_field_name("alternative").is_some() as u32,
            (Lang::Rust, "match_arm") => {
                // `_` and a lone lowercase binding (`other =>`) without a guard are the default arm.
                let pattern = node.child_by_field_name("pattern");
                let default = pattern.is_some_and(|p| {
                    let raw = text(p, src).trim();
                    let binding = p.named_child_count() == 1
                        && p.named_child(0).is_some_and(|c| c.kind() == "identifier")
                        && raw.starts_with(|c: char| c.is_lowercase() || c == '_');
                    p.child_by_field_name("condition").is_none() && (raw == "_" || binding)
                });
                (!default) as u32
            }
            (Lang::Rust, "let_chain") => {
                let mut cursor = node.walk();
                let joins = node.children(&mut cursor).filter(|c| matches!(c.kind(), "&&" | "||")).count();
                joins as u32
            }
            (Lang::Rust | Lang::Java | Lang::Go, "binary_expression") => matches!(op(), "&&" | "||") as u32,
            (Lang::TypeScript | Lang::Tsx, "binary_expression") => matches!(op(), "&&" | "||" | "??") as u32,
            (Lang::TypeScript | Lang::Tsx, "if_statement" | "for_statement" | "for_in_statement" | "while_statement"
                | "do_statement" | "ternary_expression" | "catch_clause" | "switch_case") => 1,
            (Lang::Java, "if_statement" | "for_statement" | "enhanced_for_statement" | "while_statement" | "do_statement"
                | "ternary_expression" | "catch_clause" | "guard") => 1,
            (Lang::Java, "switch_label") => {
                // `default` and `case null, default` are the default arm; `case 1, 2` counts once.
                let mut cursor = node.walk();
                let default = text(node, src).trim_start().starts_with("default")
                    || node.children(&mut cursor).any(|c| text(c, src) == "default");
                (!default) as u32
            }
            (Lang::Go, "if_statement" | "for_statement" | "expression_case" | "type_case" | "communication_case") => 1,
            (Lang::Swift, "if_statement" | "guard_statement" | "while_statement") => {
                // The grammar flattens every clause into `condition` fields; the clauses are
                // separated by direct anonymous `,` children (the body's commas sit deeper).
                let mut cursor = node.walk();
                let commas = node.children(&mut cursor).filter(|c| !c.is_named() && c.kind() == ",").count();
                1 + commas as u32
            }
            (Lang::Swift, "for_statement" | "repeat_while_statement" | "ternary_expression" | "catch_block"
                | "conjunction_expression" | "disjunction_expression" | "nil_coalescing_expression") => 1,
            (Lang::Swift, "switch_entry") => {
                let mut cursor = node.walk();
                let kinds: Vec<&str> = node.children(&mut cursor).map(|c| c.kind()).collect();
                let case = !kinds.contains(&"default_keyword") as u32;
                case + kinds.contains(&"where_keyword") as u32
            }
            _ => 0,
        }
    }

    /// `&&`/`||` operators this node contributes to a combined condition.
    fn logical_ops(&self, node: Node) -> u32 {
        match (self.lang, node.kind()) {
            (Lang::Rust, "let_chain") => self.decision(node),
            (Lang::Swift, "conjunction_expression" | "disjunction_expression") => 1,
            (Lang::Swift, _) => 0,
            (_, "binary_expression") => matches!(field_text(node, "operator", self.src).unwrap_or(""), "&&" | "||") as u32,
            _ => 0,
        }
    }

    fn if_kind(&self) -> &'static str {
        if self.lang == Lang::Rust { "if_expression" } else { "if_statement" }
    }

    /// The `if` that an `else` continues with, when this `if` has one.
    fn else_if(&self, node: Node<'a>) -> Option<Node<'a>> {
        let next = match self.lang {
            Lang::Rust | Lang::TypeScript | Lang::Tsx => node.child_by_field_name("alternative")?.named_child(0)?,
            Lang::Java | Lang::Go => node.child_by_field_name("alternative")?,
            Lang::Swift => {
                let mut cursor = node.walk();
                let found = node.named_children(&mut cursor).find(|c| c.kind() == "if_statement")?;
                found
            }
        };
        (next.kind() == self.if_kind()).then_some(next)
    }

    /// True for an `if` reached through the `else` of another `if`.
    fn continues_else_if(&self, node: Node<'a>) -> bool {
        if node.kind() != self.if_kind() {
            return false;
        }
        let owner = match self.lang {
            Lang::Rust | Lang::TypeScript | Lang::Tsx => node.parent().filter(|p| p.kind() == "else_clause").and_then(|p| p.parent()),
            Lang::Java | Lang::Go | Lang::Swift => node.parent(),
        };
        owner.is_some_and(|o| o.kind() == self.if_kind() && self.else_if(o).is_some_and(|n| n.id() == node.id()))
    }

    /// Control flow that opens one nesting level for the function it adds to.
    fn nests(&self, node: Node<'a>) -> bool {
        let kind = node.kind();
        let opens = match self.lang {
            Lang::Rust => matches!(kind, "if_expression" | "while_expression" | "for_expression" | "loop_expression" | "match_expression" | "closure_expression"),
            Lang::TypeScript | Lang::Tsx => matches!(kind, "if_statement" | "for_statement" | "for_in_statement" | "while_statement" | "do_statement"
                | "switch_statement" | "catch_clause" | "ternary_expression" | "arrow_function" | "function_expression" | "generator_function"),
            Lang::Java => matches!(kind, "if_statement" | "for_statement" | "enhanced_for_statement" | "while_statement" | "do_statement"
                | "switch_expression" | "catch_clause" | "ternary_expression" | "lambda_expression"),
            Lang::Go => matches!(kind, "if_statement" | "for_statement" | "expression_switch_statement" | "type_switch_statement" | "select_statement" | "func_literal"),
            Lang::Swift => matches!(kind, "if_statement" | "for_statement" | "while_statement" | "repeat_while_statement" | "switch_statement"
                | "catch_block" | "ternary_expression" | "lambda_literal"),
        };
        opens && !self.continues_else_if(node)
    }

    /// Declared parameters of a function-like node.
    fn params(&self, node: Node<'a>) -> u32 {
        let listed = |list: Node, skip: &[&str]| {
            let mut cursor = list.walk();
            let count = list.named_children(&mut cursor).filter(|c| !c.kind().contains("comment") && !skip.contains(&c.kind())).count();
            count as u32
        };
        let field = node.child_by_field_name("parameters");
        match self.lang {
            Lang::Rust => field.map_or(0, |p| listed(p, &["self_parameter", "attribute_item"])),
            Lang::TypeScript | Lang::Tsx => field.map_or(node.child_by_field_name("parameter").is_some() as u32, |p| listed(p, &[])),
            Lang::Java => field.map_or(0, |p| if p.kind() == "identifier" { 1 } else { listed(p, &["receiver_parameter"]) }),
            Lang::Go => field.map_or(0, |p| {
                let mut cursor = p.walk();
                let total: usize = p
                    .named_children(&mut cursor)
                    .filter(|c| c.kind().ends_with("parameter_declaration"))
                    .map(|c| c.children_by_field_name("name", &mut c.walk()).count().max(1))
                    .sum();
                total as u32
            }),
            Lang::Swift => {
                let mut cursor = node.walk();
                let direct = node.children(&mut cursor).filter(|c| c.kind() == "parameter").count() as u32;
                let closure = node
                    .child_by_field_name("type")
                    .filter(|t| t.kind() == "lambda_function_type")
                    .and_then(|t| t.named_child(0))
                    .filter(|l| l.kind() == "lambda_function_type_parameters")
                    .map_or(0, |l| listed(l, &[]));
                direct + closure
            }
        }
    }

    /// The nodes that make up an `if` condition, in source order.
    fn condition_parts(&self, node: Node<'a>) -> Vec<Node<'a>> {
        let mut cursor = node.walk();
        if self.lang != Lang::Swift {
            return node.children_by_field_name("condition", &mut cursor).collect();
        }
        // Swift exposes only fragments as `condition` fields (`if let a` yields `let`), so take
        // everything between the keyword and the body.
        node.children(&mut cursor).skip(1).take_while(|c| !matches!(c.kind(), "{" | "statements")).collect()
    }

    /// True when the condition introduces a name that only one branch can read.
    fn condition_binds(&self, node: Node<'a>) -> bool {
        self.condition_parts(node).iter().any(|part| {
            let raw = text(*part, self.src);
            match self.lang {
                Lang::Rust => part.kind().starts_with("let_"),
                Lang::Swift => part.kind() == "value_binding_pattern" || part.kind() == "pattern" || matches!(raw, "let" | "var" | "case"),
                Lang::Java => word_present(raw, "instanceof"),
                _ => false,
            }
        })
    }

    fn pattern(&mut self, rule: &'static str, node: Node, row: Option<usize>, detail: String) {
        self.patterns.push(Pattern { rule, line: node.start_position().row + 1, row, detail });
    }

    /// Record the pattern leads that start at this node.
    fn find_patterns(&mut self, node: Node<'a>, row: Option<usize>) {
        let src = self.src;
        let same = |a: Node, b: Node| pure(a, src) && pure(b, src) && squeezed(a, src) == squeezed(b, src);
        let pair = |first: &str, second: &str| node.child_by_field_name(first).zip(node.child_by_field_name(second));
        let kind = node.kind();
        // A right operand followed by `!`, `.`, `(` or `[` is the head of a longer expression
        // that the grammar split off (TypeScript `a !== a!.trim()`), so the sides are not the same.
        let continues = |operand: Node| matches!(src[operand.end_byte()..].iter().find(|b| !b.is_ascii_whitespace()), Some(b'!' | b'.' | b'(' | b'['))
            && !src[operand.end_byte()..].iter().skip_while(|b| b.is_ascii_whitespace()).take(2).eq(b"!=".iter());
        if kind == "binary_expression" && self.lang != Lang::Swift {
            let op = field_text(node, "operator", src).unwrap_or("");
            let equality = matches!(op, "==" | "!=" | "===" | "!==");
            let nan_test = equality && {
                let line = String::from_utf8_lossy(src).lines().nth(node.start_position().row).unwrap_or("").to_lowercase();
                FLOAT_WORDS.iter().any(|w| line.contains(w))
            };
            if let Some((left, _)) = pair("left", "right").filter(|(l, r)| FIXED_WHEN_IDENTICAL.contains(&op) && !nan_test && !continues(*r) && same(*l, *r)) {
                let note = if equality { "; a deliberate NaN test is the one valid use" } else { "" };
                self.pattern("identical_operands", node, row, format!("both sides of `{op}` are `{}`{note}", text(left, src).trim()));
            }
        }
        let assigned = match (self.lang, kind) {
            (Lang::Rust | Lang::TypeScript | Lang::Tsx, "assignment_expression") => pair("left", "right"),
            (Lang::Java, "assignment_expression") | (Lang::Go, "assignment_statement") => {
                pair("left", "right").filter(|_| field_text(node, "operator", src) == Some("="))
            }
            (Lang::Swift, "assignment") => {
                let mut cursor = node.walk();
                let plain = node.children(&mut cursor).any(|c| text(c, src) == "=");
                pair("target", "result").filter(|_| plain)
            }
            _ => None,
        };
        if let Some((left, _)) = assigned.filter(|(l, r)| same(*l, *r)) {
            self.pattern("self_assignment", node, row, format!("`{}` is assigned to itself", text(left, src).trim()));
        }
        let branches = match (self.lang, kind) {
            (Lang::TypeScript | Lang::Tsx | Lang::Java, "ternary_expression") => pair("consequence", "alternative"),
            (Lang::Swift, "ternary_expression") => pair("if_true", "if_false"),
            (Lang::Swift, "if_statement") => {
                let mut cursor = node.walk();
                let bodies: Vec<Node> = node.named_children(&mut cursor).filter(|c| c.kind() == "statements").collect();
                (bodies.len() == 2 && self.else_if(node).is_none()).then(|| (bodies[0], bodies[1]))
            }
            (Lang::Rust | Lang::TypeScript | Lang::Tsx, k) if k == self.if_kind() => {
                node.child_by_field_name("consequence").zip(node.child_by_field_name("alternative").and_then(|a| a.named_child(0)))
            }
            (Lang::Java | Lang::Go, "if_statement") => pair("consequence", "alternative"),
            _ => None,
        };
        // Branches are compared as text even when they call functions: the same call in both is the finding.
        let empty = |n: Node| squeezed(n, src).trim_matches(['{', '}']).is_empty();
        let binds = kind == self.if_kind() && self.condition_binds(node);
        if branches.is_some_and(|(a, b)| !binds && b.kind() != self.if_kind() && !empty(a) && squeezed(a, src) == squeezed(b, src)) {
            self.pattern("duplicate_branches", node, row, "both branches are the same code".into());
        }
        if kind == self.if_kind() && !self.continues_else_if(node) {
            let mut seen: Vec<String> = Vec::new();
            let mut link = Some(node);
            while let Some(current) = link {
                let parts = self.condition_parts(current);
                let condition = parts.iter().all(|p| pure(*p, src)).then(|| parts.iter().map(|p| squeezed(*p, src)).collect::<Vec<_>>().join(" "));
                if let Some(text) = condition.filter(|t| !t.is_empty()) {
                    if seen.contains(&text) {
                        self.pattern("repeated_condition", current, row, "this condition repeats an earlier one in the same else-if chain".into());
                    }
                    seen.push(text);
                }
                link = self.else_if(current);
            }
        }
    }

    fn test_reason(&self, node: Node, name: &str, in_test_scope: Option<&str>) -> Option<String> {
        let src = self.src;
        match self.lang {
            Lang::Rust => {
                // A closure row takes its attributes from the enclosing item (`#[cfg(test)] static`).
                let mut item = node;
                while node.kind() == "closure_expression" && !item.kind().ends_with("_item") {
                    let Some(parent) = item.parent() else { break };
                    item = parent;
                }
                for (path, args) in rust_preceding_attrs(item, src) {
                    if rust_attr_marks_test(&path) {
                        return Some(format!("#[{path}] attribute"));
                    }
                    if rust_attr_is_cfg_test(&path, &args) {
                        return Some("#[cfg(test)] item".into());
                    }
                }
            }
            Lang::Java => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor).filter(|c| c.kind() == "modifiers") {
                    let mut inner = child.walk();
                    for ann in child.children(&mut inner) {
                        if matches!(ann.kind(), "annotation" | "marker_annotation") {
                            let raw = field_text(ann, "name", src).unwrap_or("");
                            let short = raw.rsplit('.').next().unwrap_or(raw);
                            if matches!(short, "Test" | "ParameterizedTest" | "RepeatedTest" | "TestFactory" | "TestTemplate") {
                                return Some(format!("@{short} annotation"));
                            }
                        }
                    }
                }
            }
            Lang::TypeScript | Lang::Tsx if self.ts_test_callback(node) => {
                return Some("describe/it/test callback".into());
            }
            Lang::Swift => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "modifiers" || child.kind() == "attribute" {
                        let raw = text(child, src);
                        if raw.split_whitespace().any(|t| t == "@Test" || t.starts_with("@Test(")) {
                            return Some("@Test attribute".into());
                        }
                    }
                }
                if in_test_scope == Some("xctest") && name.starts_with("test") {
                    return Some("test method in XCTestCase subclass".into());
                }
            }
            _ => {}
        }
        in_test_scope.filter(|s| *s != "xctest").map(str::to_string)
    }

    /// Test context that a scope node imposes on everything inside it.
    fn scope_test_context(&self, node: Node) -> Option<String> {
        let src = self.src;
        match (self.lang, node.kind()) {
            (Lang::Rust, "mod_item" | "impl_item" | "function_item") => {
                for (path, args) in rust_preceding_attrs(node, src) {
                    if rust_attr_is_cfg_test(&path, &args) {
                        return Some("inside #[cfg(test)] item".into());
                    }
                }
                None
            }
            (Lang::Swift, "class_declaration") => {
                let mut cursor = node.walk();
                let xctest = node
                    .children(&mut cursor)
                    .any(|c| c.kind() == "inheritance_specifier" && word_present(text(c, src), "XCTestCase"));
                xctest.then(|| "xctest".to_string())
            }
            _ => None,
        }
    }

    /// Record `mod name;` (no body) with the files Rust would load for it.
    fn out_of_line_module(&mut self, node: Node, file: &str, test_ctx: &Option<String>) {
        if self.lang != Lang::Rust || node.kind() != "mod_item" || node.child_by_field_name("body").is_some() {
            return;
        }
        let Some(name) = field_text(node, "name", self.src) else { return };
        let attrs = rust_preceding_attrs(node, self.src);
        let under_test = test_ctx.is_some() || attrs.iter().any(|(p, a)| rust_attr_is_cfg_test(p, a));
        let path = Path::new(file);
        let dir = path.parent().unwrap_or(Path::new(""));
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
        let explicit = attrs.iter().find(|(p, _)| p.starts_with("path")).and_then(|(p, _)| {
            p.split_once('=').map(|(_, v)| v.trim().trim_matches('"').to_string())
        });
        // Crate roots and mod.rs files own their directory; other files own `dir/stem/`.
        let mut base = if self.crate_root || stem == "mod" { dir.to_path_buf() } else { dir.join(stem) };
        for m in &self.mod_path {
            base = base.join(m);
        }
        let candidates = match explicit {
            // `#[path]` is relative to the file's directory, or inside an inline `mod`
            // to that module's directory.
            Some(rel) if self.mod_path.is_empty() => vec![dir.join(rel)],
            Some(rel) => vec![base.join(rel)],
            None => vec![base.join(format!("{name}.rs")), base.join(name).join("mod.rs")],
        };
        let normalized = candidates.iter().map(|c| c.to_string_lossy().replace('\\', "/")).collect();
        self.modules.push((normalized, under_test));
    }

    fn walk(&mut self, node: Node<'a>, current: Option<usize>, test_ctx: Option<String>, file: &str, depth: u32, condition: Option<usize>) {
        self.out_of_line_module(node, file, &test_ctx);
        let is_inline_mod = self.lang == Lang::Rust && node.kind() == "mod_item" && node.child_by_field_name("body").is_some();
        if is_inline_mod {
            self.mod_path.push(field_text(node, "name", self.src).unwrap_or("").to_string());
        }
        let (mut depth, mut condition, mut opens_chunk) = (depth, condition, false);
        let (current, test_ctx, pushed) = if let Some((short, name_node)) = self.function_row(node, current) {
            let qualified = self.scope.iter().cloned().chain(std::iter::once(short.clone())).collect::<Vec<_>>().join(".");
            let file_ctx = self.scope_test_context(node).or(test_ctx.clone());
            let reason = self.test_reason(node, &short, file_ctx.as_deref());
            self.rows.push(Row {
                name: qualified,
                line: name_node.start_position().row + 1,
                end_line: node.end_position().row + 1,
                cc: 1,
                nodes: 0,
                test_reason: reason.clone(),
                kinds: Vec::new(),
                max_nesting: 0,
                chunk_depth: 0,
                bumps: 0,
                condition_operators: 0,
                params: self.params(node),
            });
            (depth, condition) = (0, None);
            self.scope.push(short);
            // A test function's nested helpers are test code too.
            let inherited = reason.or(file_ctx.filter(|c| c != "xctest"));
            (Some(self.rows.len() - 1), inherited, true)
        } else if let Some(scope) = self.scope_name(node) {
            let ctx = self.scope_test_context(node).or(test_ctx);
            self.scope.push(scope);
            (current, ctx, true)
        } else {
            let add = self.decision(node);
            self.find_patterns(node, current);
            if let Some(i) = current {
                let nests = self.nests(node);
                if nests || CONDITION_BOUNDARIES.iter().any(|k| node.kind().contains(k)) || node.kind().ends_with("_statement") {
                    condition = None;
                }
                let ops = self.logical_ops(node);
                if ops > 0 {
                    let index = condition.unwrap_or_else(|| {
                        self.conditions.push(0);
                        self.conditions.len() - 1
                    });
                    self.conditions[index] += ops;
                    condition = Some(index);
                }
                let combined = condition.map_or(0, |c| self.conditions[c]);
                let row = &mut self.rows[i];
                row.condition_operators = row.condition_operators.max(combined);
                if nests {
                    depth += 1;
                    opens_chunk = depth == 1;
                    row.max_nesting = row.max_nesting.max(depth);
                    row.chunk_depth = if opens_chunk { 1 } else { row.chunk_depth.max(depth) };
                }
                row.cc += add;
                if node.is_named() {
                    row.nodes += 1;
                    row.kinds.push(node.kind_id());
                }
            } else {
                self.unowned += add;
            }
            (current, test_ctx, false)
        };
        let mut cursor = node.walk();
        let children: Vec<Node<'a>> = node.children(&mut cursor).collect();
        for child in children {
            self.walk(child, current, test_ctx.clone(), file, depth, condition);
        }
        if let Some(i) = current.filter(|_| opens_chunk) {
            self.rows[i].bumps += (self.rows[i].chunk_depth >= 2) as u32;
        }
        if pushed {
            self.scope.pop();
        }
        if is_inline_mod {
            self.mod_path.pop();
        }
    }
}

/// Base type of a Go receiver: `(s *Stack[T])` -> `Stack`, `(x *pkg.T)` -> `T`.
fn go_receiver_type(receiver: Node, src: &[u8]) -> String {
    let mut cursor = receiver.walk();
    let param = receiver.named_children(&mut cursor).find(|c| c.kind() == "parameter_declaration");
    let mut ty = param.and_then(|p| p.child_by_field_name("type"));
    while let Some(t) = ty {
        ty = match t.kind() {
            "type_identifier" => return text(t, src).to_string(),
            "pointer_type" | "parenthesized_type" => t.named_child(0),
            "generic_type" => t.child_by_field_name("type"),
            "qualified_type" => t.child_by_field_name("name"),
            _ => None,
        };
    }
    String::new()
}

/// Name node of the Swift property that owns a computed body or accessor.
fn swift_property_name(node: Node) -> Option<Node> {
    let prop = if node.kind() == "willset_didset_block" { node.parent()? } else { node };
    (prop.kind() == "property_declaration").then(|| prop.child_by_field_name("name")).flatten()
}

/// Rust files whose out-of-line modules live in their own directory.
fn rust_crate_root(root: &Path, rel: &str) -> bool {
    let path = Path::new(rel);
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
    let dir = path.parent().unwrap_or(Path::new(""));
    let dir_name = dir.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let package = dir.parent().unwrap_or(Path::new(""));
    let package_name = package.file_name().and_then(|s| s.to_str()).unwrap_or("");
    matches!(stem, "lib" | "main")
        || (dir_name == "bin" && package_name == "src")
        || (matches!(dir_name, "tests" | "examples" | "benches") && root.join(package).join("Cargo.toml").is_file())
        || (stem == "build" && root.join(dir).join("Cargo.toml").is_file())
}

fn rust_file_is_test(root: Node, src: &[u8]) -> bool {
    let mut cursor = root.walk();
    let found = root.children(&mut cursor).any(|c| {
        c.kind() == "inner_attribute_item" && {
            let (path, args) = rust_attr(text(c, src));
            rust_attr_is_cfg_test(&path, &args)
        }
    });
    found
}

fn fnv(data: &[u16]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for v in data {
        for b in v.to_le_bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
    }
    h
}

fn mix(x: u64, seed: u64) -> u64 {
    let mut z = x ^ seed.wrapping_mul(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

struct Candidate {
    lang: &'static str,
    path: String,
    function_id: String,
    shingles: Vec<u64>,
}

fn jaccard(a: &[u64], b: &[u64]) -> f64 {
    let (mut i, mut j, mut both) = (0, 0, 0usize);
    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                both += 1;
                i += 1;
                j += 1;
            }
        }
    }
    let union = a.len() + b.len() - both;
    if union == 0 { 0.0 } else { both as f64 / union as f64 }
}

/// Probability that a pair with Jaccard similarity `s` shares at least one band.
fn lsh_recall(s: f64, rows: usize, bands: usize) -> f64 {
    1.0 - (1.0 - s.powi(rows as i32)).powi(bands as i32)
}

/// (rows per band, bands) with the most rows per band (fewest false candidates)
/// that still finds a pair exactly at `threshold` with TARGET_RECALL, using at most
/// MAX_MINHASHES hashes. None means no banding reaches the target: compare all pairs.
fn lsh_params(threshold: f64) -> Option<(usize, usize)> {
    (1..=16usize).rev().find_map(|rows| {
        let p = threshold.powi(rows as i32);
        if p <= 0.0 {
            return None;
        }
        let bands = if p >= 1.0 { 1 } else { ((1.0 - TARGET_RECALL).ln() / (1.0 - p).ln()).ceil() as usize };
        (rows * bands <= MAX_MINHASHES).then_some((rows, bands))
    })
}

/// MinHash/LSH candidate generation (or all pairs), then exact Jaccard on node-kind shingles.
fn duplicate_pairs(cands: &[Candidate], threshold: f64, max_pairs: usize, banding: Option<(usize, usize)>) -> (Vec<serde_json::Value>, usize) {
    let mut buckets: HashMap<(usize, u64), Vec<usize>> = HashMap::new();
    match banding {
        Some((rows, bands)) => {
            for (idx, c) in cands.iter().enumerate() {
                let sig: Vec<u64> = (0..(rows * bands) as u64)
                    .map(|seed| c.shingles.iter().map(|s| mix(*s, seed + 1)).min().unwrap_or(u64::MAX))
                    .collect();
                for band in 0..bands {
                    let slice = &sig[band * rows..(band + 1) * rows];
                    let key = slice.iter().fold(0u64, |acc, v| mix(acc ^ v, band as u64 + 101));
                    buckets.entry((band, key)).or_default().push(idx);
                }
            }
        }
        None => {
            buckets.insert((0, 0), (0..cands.len()).collect());
        }
    }
    let mut seen = HashSet::new();
    let mut pairs = Vec::new();
    for members in buckets.values() {
        for x in 0..members.len() {
            for y in (x + 1)..members.len() {
                let (a, b) = (members[x].min(members[y]), members[x].max(members[y]));
                if a == b || cands[a].lang != cands[b].lang || !seen.insert((a, b)) {
                    continue;
                }
                let sim = jaccard(&cands[a].shingles, &cands[b].shingles);
                if sim >= threshold {
                    pairs.push((sim, a, b));
                }
            }
        }
    }
    pairs.sort_by(|p, q| q.0.partial_cmp(&p.0).unwrap().then(p.1.cmp(&q.1)).then(p.2.cmp(&q.2)));
    let total = pairs.len();
    let out = pairs
        .into_iter()
        .take(max_pairs)
        .map(|(sim, a, b)| {
            serde_json::json!({
                "similarity": (sim * 1e4).round() / 1e4,
                "language": cands[a].lang,
                "a": {"path": cands[a].path, "function_id": cands[a].function_id},
                "b": {"path": cands[b].path, "function_id": cands[b].function_id},
            })
        })
        .collect();
    (out, total)
}

fn safe_relative(rel: &str) -> bool {
    let p = Path::new(rel);
    !p.is_absolute() && p.components().all(|c| matches!(c, Component::Normal(_) | Component::CurDir))
}

struct Options {
    root: PathBuf,
    paths: Vec<String>,
    duplicates: bool,
    similarity: f64,
    min_nodes: u32,
    max_pairs: usize,
}

fn parse_args() -> Result<Options, String> {
    let mut args = std::env::args().skip(1);
    let mut opts = Options {
        root: PathBuf::new(),
        paths: Vec::new(),
        duplicates: false,
        similarity: 0.8,
        min_nodes: 40,
        max_pairs: 200,
    };
    let mut root = None;
    while let Some(a) = args.next() {
        let mut value = |flag: &str| args.next().ok_or_else(|| format!("{flag} needs a value"));
        match a.as_str() {
            "--root" => root = Some(PathBuf::from(value("--root")?)),
            "--duplicates" => opts.duplicates = true,
            "--similarity" => {
                opts.similarity = value("--similarity")?.parse().map_err(|_| "--similarity must be a number")?
            }
            "--min-nodes" => opts.min_nodes = value("--min-nodes")?.parse().map_err(|_| "--min-nodes must be an integer")?,
            "--max-pairs" => opts.max_pairs = value("--max-pairs")?.parse().map_err(|_| "--max-pairs must be an integer")?,
            "--" => opts.paths.extend(args.by_ref()),
            "-h" | "--help" => return Err(String::from("help")),
            "--version" => return Err(String::from("version")),
            other if other.starts_with("--") => return Err(format!("unknown flag {other}")),
            other => opts.paths.push(other.to_string()),
        }
    }
    opts.root = root.ok_or("--root is required")?;
    if !(0.0..=1.0).contains(&opts.similarity) {
        return Err("--similarity must be within [0,1]".into());
    }
    Ok(opts)
}

fn main() {
    let versions = locked_versions();
    let analyzer = serde_json::json!({
        "name": "code-audit-complexity",
        "version": env!("CARGO_PKG_VERSION"),
        "parser": format!("tree-sitter {}", versions.get("tree-sitter").map(String::as_str).unwrap_or("unknown")),
        "grammars": {
            "rust": versions.get("tree-sitter-rust"),
            "typescript": versions.get("tree-sitter-typescript"),
            "java": versions.get("tree-sitter-java"),
            "go": versions.get("tree-sitter-go"),
            "swift": versions.get("tree-sitter-swift"),
        },
        "method": "tree-sitter-decisions-v1",
        "structure_method": "tree-sitter-structure-v1",
    });
    let opts = match parse_args() {
        Ok(o) => o,
        Err(e) if e == "help" => {
            println!("usage: code-audit-complexity --root <dir> [--duplicates] [--similarity 0.8] [--min-nodes 40] [--max-pairs 200] -- <root-relative files>\n\nSee the module documentation in src/main.rs for counting rules.");
            return;
        }
        Err(e) if e == "version" => {
            println!("{}", serde_json::to_string_pretty(&analyzer).unwrap());
            return;
        }
        Err(e) => {
            println!("{}", serde_json::json!({"status": "invalid", "error": e, "analyzer": analyzer}));
            std::process::exit(2);
        }
    };
    let mut files = Vec::new();
    let mut candidates = Vec::new();
    for rel in &opts.paths {
        if !safe_relative(rel) {
            files.push(serde_json::json!({"path": rel, "error": "path must be root-relative without '..'"}));
            continue;
        }
        let Some(lang) = Lang::from_path(rel) else {
            files.push(serde_json::json!({"path": rel, "error": "unsupported language for this analyzer"}));
            continue;
        };
        let raw = match std::fs::read(opts.root.join(rel)) {
            Ok(r) => r,
            Err(e) => {
                files.push(serde_json::json!({"path": rel, "error": format!("cannot read source: {e}")}));
                continue;
            }
        };
        let mut parser = Parser::new();
        if let Err(e) = parser.set_language(&lang.grammar()) {
            files.push(serde_json::json!({"path": rel, "error": format!("grammar unavailable: {e}")}));
            continue;
        }
        let Some(tree) = parser.parse(&raw, None) else {
            files.push(serde_json::json!({"path": rel, "error": "parser returned no tree"}));
            continue;
        };
        let root = tree.root_node();
        let mut walker = Walker::new(lang, &raw, lang == Lang::Rust && rust_crate_root(&opts.root, rel));
        let file_ctx = (lang == Lang::Rust && rust_file_is_test(root, &raw)).then(|| "file has #![cfg(test)]".to_string());
        walker.walk(root, None, file_ctx, rel, 0, None);
        let mut functions = Vec::new();
        for row in &walker.rows {
            let function_id = format!("{}:{}", row.name, row.line);
            if opts.duplicates && row.nodes >= opts.min_nodes && row.kinds.len() >= SHINGLE {
                let mut shingles: Vec<u64> = row.kinds.windows(SHINGLE).map(fnv).collect();
                shingles.sort_unstable();
                shingles.dedup();
                candidates.push(Candidate { lang: lang.name(), path: rel.clone(), function_id: function_id.clone(), shingles });
            }
            functions.push(serde_json::json!({
                "name": row.name,
                "line": row.line,
                "end_line": row.end_line,
                "function_id": function_id,
                "cc": row.cc,
                "nodes": row.nodes,
                "test_reason": row.test_reason,
                "max_nesting": row.max_nesting,
                "bumps": row.bumps,
                "condition_operators": row.condition_operators,
                "params": row.params,
            }));
        }
        let patterns: Vec<serde_json::Value> = walker
            .patterns
            .iter()
            .map(|p| {
                let function_id = p.row.map(|i| format!("{}:{}", walker.rows[i].name, walker.rows[i].line));
                serde_json::json!({"rule": p.rule, "line": p.line, "function_id": function_id, "detail": p.detail})
            })
            .collect();
        files.push(serde_json::json!({
            "path": rel,
            "language": lang.name(),
            "grammar": format!("{} {}", lang.grammar_crate(), versions.get(lang.grammar_crate()).map(String::as_str).unwrap_or("unknown")),
            "sha256": format!("{:x}", Sha256::digest(&raw)),
            "parse_errors": root.has_error(),
            "functions": functions,
            "unowned_decisions": walker.unowned,
            "patterns": patterns,
            "modules": walker.modules.iter().map(|(files, test)| serde_json::json!({"candidates": files, "under_test": test})).collect::<Vec<_>>(),
        }));
    }
    let mut report = serde_json::json!({
        "schema": "code-audit.complexity-native.v1",
        "status": "measured",
        "analyzer": analyzer,
        "files": files,
    });
    if opts.duplicates {
        let banding = lsh_params(opts.similarity);
        let (pairs, total) = duplicate_pairs(&candidates, opts.similarity, opts.max_pairs, banding);
        let (search, recall) = match banding {
            Some((rows, bands)) => (
                format!("MinHash LSH, {bands} bands x {rows} rows derived from the threshold"),
                lsh_recall(opts.similarity, rows, bands),
            ),
            None => ("all pairs".to_string(), 1.0),
        };
        report["duplicates"] = serde_json::json!({
            "method": format!("Jaccard similarity of {SHINGLE}-node-kind shingles; {search}; exact verification of candidates"),
            "similarity_threshold": opts.similarity,
            "min_nodes": opts.min_nodes,
            "functions_compared": candidates.len(),
            "candidate_pairs_found": total,
            "estimated_recall_at_threshold": (recall * 1e4).floor() / 1e4,
            "recall_note": "Probability that a pair exactly at the threshold is found; more similar pairs are found more reliably.",
            "pairs_reported": pairs.len(),
            "pairs": pairs,
            "note": "Structural candidates only. Confirm the fragments implement one policy that should change together before sharing them.",
        });
    }
    println!("{}", serde_json::to_string_pretty(&report).unwrap());
}
