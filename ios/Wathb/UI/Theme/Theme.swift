import SwiftUI
import UIKit

// Wathb brand (android ui/theme): Deep Teal #006D6B, Teal #0EA5A3, Gold #F4B432,
// Warm Cream #FEF3D7, typeface Thmanyah Sans with no letter spacing.

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255)
    }

    /// A colour with a light and a dark value.
    init(light: UInt32, dark: UInt32) {
        self.init(UIColor { $0.userInterfaceStyle == .dark ? UIColor(Color(hex: dark)) : UIColor(Color(hex: light)) })
    }
}

enum Brand {
    static let deepTeal = Color(hex: 0x006D6B)
    static let teal = Color(hex: 0x0EA5A3)
    static let gold = Color(hex: 0xF4B432)
    static let cream = Color(hex: 0xFEF3D7)

    static let primary = Color(light: 0x006D6B, dark: 0x0EA5A3)
    static let tertiary = Color(light: 0x0EA5A3, dark: 0xB2E8E7)
    static let secondary = Color(light: 0xC48A14, dark: 0xF4B432)
    static let background = Color(light: 0xFEFAF5, dark: 0x1C1B1F)
    static let card = Color(light: 0xFFFFFF, dark: 0x2A292E)
    static let field = Color(light: 0xFFFFFF, dark: 0x232227)
    static let border = Color(light: 0xE6E0E9, dark: 0x49454F)
    static let muted = Color(light: 0x49454F, dark: 0xCAC4D0)
    static let error = Color(light: 0xB3261E, dark: 0xF2B8B5)
    static let errorContainer = Color(light: 0xF9DEDC, dark: 0x601410)
    static let successContainer = Color(light: 0xD7F3F2, dark: 0x0B3F3E)
    static let warningContainer = Color(light: 0xFDEAB0, dark: 0x4A3A10)
}

enum FontWeightName: String {
    case light = "Light", regular = "Regular", medium = "Medium", bold = "Bold", black = "Black"
}

extension Font {
    /// Thmanyah Sans; scales with the user's text size.
    static func wathb(_ size: CGFloat, _ weight: FontWeightName = .regular) -> Font {
        .custom("thmanyahsans-\(weight.rawValue)", size: size, relativeTo: size >= 20 ? .title2 : size >= 16 ? .body : .footnote)
    }
}

enum Theme {
    /// Navigation and tab bars use the brand font too.
    static func applyAppearance() {
        let title = UIFont(name: "thmanyahsans-Bold", size: 18) ?? .boldSystemFont(ofSize: 18)
        let large = UIFont(name: "thmanyahsans-Black", size: 30) ?? .boldSystemFont(ofSize: 30)
        let nav = UINavigationBarAppearance()
        nav.configureWithDefaultBackground()
        nav.titleTextAttributes = [.font: title]
        nav.largeTitleTextAttributes = [.font: large]
        let button = UIBarButtonItemAppearance()
        button.normal.titleTextAttributes = [.font: UIFont(name: "thmanyahsans-Medium", size: 16) ?? .systemFont(ofSize: 16)]
        nav.buttonAppearance = button
        nav.backButtonAppearance = button
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav

        let tabFont = UIFont(name: "thmanyahsans-Medium", size: 11) ?? .systemFont(ofSize: 11)
        let tab = UITabBarAppearance()
        tab.configureWithDefaultBackground()
        for layout in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            layout.normal.titleTextAttributes = [.font: tabFont]
            layout.selected.titleTextAttributes = [.font: tabFont]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab

        let segFont = UIFont(name: "thmanyahsans-Medium", size: 15) ?? .systemFont(ofSize: 15)
        UISegmentedControl.appearance().setTitleTextAttributes([.font: segFont], for: .normal)
    }
}
