import "@testing-library/jest-dom";

if (!Element.prototype.scrollIntoView) {
  // jsdom doesn't implement scrollIntoView; LogPanel uses it for autoscroll.
  Element.prototype.scrollIntoView = () => {};
}
