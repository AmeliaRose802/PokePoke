import "@testing-library/jest-dom";

if (!Element.prototype.scrollIntoView) {
  // jsdom doesn't implement scrollIntoView; keep polyfill for any third-party usage.
  Element.prototype.scrollIntoView = () => {};
}
