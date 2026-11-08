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
//!   match arm except a bare `_` arm without a guard, each `&&`/`||`.
//!   `loop` (no condition) and `?` are not counted.
//! - TypeScript: `if`, `for`, `for in/of`, `while`, `do`, `?:`, `catch`, each
//!   non-default `case`, each `&&`/`||`/`??`. Optional chaining is not counted.
//! - Java: `if`, `for`, enhanced `for`, `while`, `do`, `?:`, `catch`, each
//!   non-default switch label, pattern guards, each `&&`/`||`.
//! - Go: `if`, `for`, each non-default `case` in expression, type and select
//!   switches, each `&&`/`||`.
//! - Swift: `if`, `guard`, `for`, `while`, `repeat`, `?:`, `catch`, each
//!   non-default `case`, each `&&`/`||`/`??`, and each extra comma-separated
//!   condition in `if`/`guard`/`while`.
//!
//! Named functions are measured separately and do not add to an enclosing
//! function. Anonymous closures, lambdas, arrow functions and function
//! literals add their decisions to the enclosing named function, because in
//! these languages they routinely carry control flow inline. An arrow
//! function or function expression bound to a variable or class field is
//! treated as a named function.

use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::path::{Component, Path, PathBuf};
use tree_sitter::{Node, Parser};

const LOCKFILE: &str = include_str!("../Cargo.lock");
const SHINGLE: usize = 5;
const MINHASHES: usize = 32;
const BANDS: usize = 8;

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

fn rust_attr_is_cfg_test(path: &str, args: &str) -> bool {
    path == "cfg" && word_present(args, "test") && !args.replace(' ', "").contains("not(test")
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
    fn new(lang: Lang, src: &'a [u8]) -> Self {
        Walker { lang, src, rows: Vec::new(), scope: Vec::new(), mod_path: Vec::new(), modules: Vec::new() }
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
            _ => None,
        }
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
                let pattern = node.child_by_field_name("pattern");
                let bare = pattern.is_some_and(|p| {
                    p.child_by_field_name("condition").is_none() && text(p, src).trim() == "_"
                });
                (!bare) as u32
            }
            (Lang::Rust | Lang::Java | Lang::Go, "binary_expression") => matches!(op(), "&&" | "||") as u32,
            (Lang::TypeScript | Lang::Tsx, "binary_expression") => matches!(op(), "&&" | "||" | "??") as u32,
            (Lang::TypeScript | Lang::Tsx, "if_statement" | "for_statement" | "for_in_statement" | "while_statement"
                | "do_statement" | "ternary_expression" | "catch_clause" | "switch_case") => 1,
            (Lang::Java, "if_statement" | "for_statement" | "enhanced_for_statement" | "while_statement" | "do_statement"
                | "ternary_expression" | "catch_clause" | "guard") => 1,
            (Lang::Java, "switch_label") => (!text(node, src).trim_start().starts_with("default")) as u32,
            (Lang::Go, "if_statement" | "for_statement" | "expression_case" | "type_case" | "communication_case") => 1,
            (Lang::Swift, "if_statement" | "guard_statement" | "while_statement") => {
                // `let x = y` is recorded as three condition fields: the binding pattern, an
                // anonymous `=` token and the value. Count named nodes, then drop the bindings.
                let mut cursor = node.walk();
                let (fields, bindings) = node
                    .children_by_field_name("condition", &mut cursor)
                    .filter(|c| c.is_named())
                    .fold((0u32, 0u32), |(f, b), c| (f + 1, b + (c.kind() == "value_binding_pattern") as u32));
                fields.saturating_sub(bindings).max(1)
            }
            (Lang::Swift, "for_statement" | "repeat_while_statement" | "ternary_expression" | "catch_block"
                | "conjunction_expression" | "disjunction_expression" | "nil_coalescing_expression") => 1,
            (Lang::Swift, "switch_entry") => {
                let mut cursor = node.walk();
                let is_default = node.children(&mut cursor).any(|c| c.kind() == "default_keyword");
                (!is_default) as u32
            }
            _ => 0,
        }
    }

    fn test_reason(&self, node: Node, name: &str, in_test_scope: Option<&str>) -> Option<String> {
        let src = self.src;
        match self.lang {
            Lang::Rust => {
                for (path, args) in rust_preceding_attrs(node, src) {
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
        let mut base = if matches!(stem, "lib" | "main" | "mod") { dir.to_path_buf() } else { dir.join(stem) };
        for m in &self.mod_path {
            base = base.join(m);
        }
        let candidates = match explicit {
            Some(rel) => vec![dir.join(rel)],
            None => vec![base.join(format!("{name}.rs")), base.join(name).join("mod.rs")],
        };
        let normalized = candidates.iter().map(|c| c.to_string_lossy().replace('\\', "/")).collect();
        self.modules.push((normalized, under_test));
    }

    fn walk(&mut self, node: Node<'a>, current: Option<usize>, test_ctx: Option<String>, file: &str) {
        self.out_of_line_module(node, file, &test_ctx);
        let is_inline_mod = self.lang == Lang::Rust && node.kind() == "mod_item" && node.child_by_field_name("body").is_some();
        if is_inline_mod {
            self.mod_path.push(field_text(node, "name", self.src).unwrap_or("").to_string());
        }
        let (current, test_ctx, pushed) = if let Some((short, name_node)) = self.named_function(node) {
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
            });
            self.scope.push(short);
            // A test function's nested helpers are test code too.
            let inherited = reason.or(file_ctx.filter(|c| c != "xctest"));
            (Some(self.rows.len() - 1), inherited, true)
        } else if let Some(scope) = self.scope_name(node) {
            let ctx = self.scope_test_context(node).or(test_ctx);
            self.scope.push(scope);
            (current, ctx, true)
        } else {
            if let Some(i) = current {
                let add = self.decision(node);
                let row = &mut self.rows[i];
                row.cc += add;
                if node.is_named() {
                    row.nodes += 1;
                    row.kinds.push(node.kind_id());
                }
            }
            (current, test_ctx, false)
        };
        let mut cursor = node.walk();
        let children: Vec<Node<'a>> = node.children(&mut cursor).collect();
        for child in children {
            self.walk(child, current, test_ctx.clone(), file);
        }
        if pushed {
            self.scope.pop();
        }
        if is_inline_mod {
            self.mod_path.pop();
        }
    }
}

fn go_receiver_type(receiver: Node, src: &[u8]) -> String {
    let mut stack = vec![receiver];
    let mut last = String::new();
    while let Some(n) = stack.pop() {
        if n.kind() == "type_identifier" {
            last = text(n, src).to_string();
        }
        let mut cursor = n.walk();
        let mut kids: Vec<Node> = n.children(&mut cursor).collect();
        kids.reverse();
        stack.extend(kids);
    }
    last
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

/// MinHash/LSH candidate generation, then exact Jaccard on node-kind shingles.
fn duplicate_pairs(cands: &[Candidate], threshold: f64, max_pairs: usize) -> (Vec<serde_json::Value>, usize) {
    let rows = MINHASHES / BANDS;
    let mut buckets: HashMap<(usize, u64), Vec<usize>> = HashMap::new();
    for (idx, c) in cands.iter().enumerate() {
        let sig: Vec<u64> = (0..MINHASHES as u64)
            .map(|seed| c.shingles.iter().map(|s| mix(*s, seed + 1)).min().unwrap_or(u64::MAX))
            .collect();
        for band in 0..BANDS {
            let slice = &sig[band * rows..(band + 1) * rows];
            let key = slice.iter().fold(0u64, |acc, v| mix(acc ^ v, band as u64 + 101));
            buckets.entry((band, key)).or_default().push(idx);
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
        let mut walker = Walker::new(lang, &raw);
        let file_ctx = (lang == Lang::Rust && rust_file_is_test(root, &raw)).then(|| "file has #![cfg(test)]".to_string());
        walker.walk(root, None, file_ctx, rel);
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
            }));
        }
        files.push(serde_json::json!({
            "path": rel,
            "language": lang.name(),
            "grammar": format!("{} {}", lang.grammar_crate(), versions.get(lang.grammar_crate()).map(String::as_str).unwrap_or("unknown")),
            "sha256": format!("{:x}", Sha256::digest(&raw)),
            "parse_errors": root.has_error(),
            "functions": functions,
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
        let (pairs, total) = duplicate_pairs(&candidates, opts.similarity, opts.max_pairs);
        report["duplicates"] = serde_json::json!({
            "method": format!("Jaccard similarity of {SHINGLE}-node-kind shingles; MinHash {MINHASHES}x{BANDS}-band candidate search, exact verification"),
            "similarity_threshold": opts.similarity,
            "min_nodes": opts.min_nodes,
            "functions_compared": candidates.len(),
            "pairs_at_or_above_threshold": total,
            "pairs_reported": pairs.len(),
            "pairs": pairs,
            "note": "Structural candidates only. Confirm the fragments implement one policy that should change together before sharing them.",
        });
    }
    println!("{}", serde_json::to_string_pretty(&report).unwrap());
}
