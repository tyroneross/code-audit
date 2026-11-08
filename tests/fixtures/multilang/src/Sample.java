package demo;

public class Sample {
    // 1 + if + && + enhanced-for + ternary = 5
    public int count(int[] xs, boolean on, boolean strict) {
        int n = 0;
        if (on && strict) {
            n = 1;
        }
        for (int x : xs) {
            n += x > 0 ? 1 : 0;
        }
        return n;
    }

    // 1 + two case labels (default free) + catch + lambda while (inline) = 5
    public int pick(int k) {
        try {
            switch (k) {
                case 1: return 10;
                case 2: return 20;
                default: return 0;
            }
        } catch (RuntimeException e) {
            Runnable r = () -> { while (false) {} };
            return -1;
        }
    }

    @Test
    public void testPick() {}
}
