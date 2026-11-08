package demo

import "testing"

func TestSize(t *testing.T) {
	if (&Box{}).Size(nil, false, false) != 0 {
		t.Fatal("bad")
	}
}
