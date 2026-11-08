package demo

type Box struct{}

// 1 + if + || + for + 2 cases (default free) = 6
func (b *Box) Size(xs []int, on bool, off bool) int {
	n := 0
	if on || off {
		n = 1
	}
	for _, x := range xs {
		switch x {
		case 1:
			n++
		case 2:
			n--
		default:
		}
	}
	return n
}

// 1 + func literal if (inline) = 2
func Apply(f func(int) int) int {
	g := func(x int) int {
		if x > 0 {
			return x
		}
		return 0
	}
	return f(g(1))
}
