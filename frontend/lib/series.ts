/**
 * Arithmetic over series the backend has already produced.
 *
 * This file used to hold a deterministic series *generator* for the mock
 * build. It is gone: every series now comes from ORION, and a helper that can
 * manufacture plausible-looking data is exactly the sort of thing that ends up
 * on screen by accident.
 */

export function mean(nums: number[]): number {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
}
