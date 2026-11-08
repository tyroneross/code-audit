export class Router {
  // 1 + if + || + ?? + ternary = 5
  route(a: boolean, b: boolean, c?: number): number {
    if (a || b) {
      return c ?? 0;
    }
    return a ? 1 : 2;
  }
}

// 1 + for + 2 non-default cases + catch + arrow-callback if (inline) = 6
export function scan(xs: number[]): number {
  let n = 0;
  for (const x of xs) {
    switch (x) {
      case 1: n++; break;
      case 2: n--; break;
      default: break;
    }
  }
  try { xs.forEach((y) => { if (y > 3) { n++; } }); } catch (e) { n = -1; }
  return n;
}

// bound arrow function is named: 1 + while + do = 3
export const spin = (k: number): number => {
  while (k > 0) { k--; }
  do { k++; } while (k < 2);
  return k;
};
