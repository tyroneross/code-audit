struct Gate {
    // 1 + if with 2 conditions (2) + guard + ?? + ternary = 6
    func check(a: Int?, b: Bool, c: Bool) -> Int {
        if b, c {
            return 1
        }
        guard let v = a else { return 0 }
        let w = a ?? 0
        return v > w ? v : w
    }

    // 1 + for + switch 2 cases (default free) + && + ternary = 6
    func spin(xs: [Int], on: Bool) -> Int {
        var n = 0
        for x in xs {
            switch x {
            case 1: n += 1
            case 2: n -= 1
            default: break
            }
        }
        return on && n > 0 ? n : 0
    }
}
