import XCTest

final class GateTests: XCTestCase {
    func testCheck() {
        XCTAssertEqual(Gate().check(a: 1, b: true, c: true), 1)
    }
}
