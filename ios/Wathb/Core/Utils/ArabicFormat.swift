import Foundation

// Same output as android ui/utils/ArabicFormat.kt.

extension String {
    /// "250" → "٢٥٠"
    var arabicDigits: String {
        String(map { c -> Character in
            guard let d = c.wholeNumberValue, c.isASCII else { return c }
            return Character(UnicodeScalar(0x0660 + d)!)
        })
    }

    /// "٤٨٢ 913" → "482913": Arabic keyboards type Arabic-Indic digits.
    var asciiDigits: String {
        String(compactMap { c -> Character? in
            guard let d = c.wholeNumberValue else { return nil }
            return Character(String(d))
        })
    }

    /// "250 ILS" from the server → "٢٥٠ ₪"
    var arabicAmount: String { replacingOccurrences(of: "ILS", with: "₪").arabicDigits }

    /// "+970599123456" → "0599123456" (how people type and read Palestinian mobiles).
    var localPhone: String {
        for prefix in ["+970", "+972"] where hasPrefix(prefix) { return "0" + dropFirst(prefix.count) }
        return self
    }
}

extension Int {
    var arabic: String { String(self).arabicDigits }
}

enum ArabicFormat {
    private static let months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                                 "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

    /// "YYYY-MM-DD" or a full ISO datetime → "١٦ أكتوبر ٢٠٢٦"
    static func date(_ iso: String?) -> String {
        guard let iso else { return "" }
        let parts = iso.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, (1...12).contains(parts[1]) else { return iso }
        return "\(parts[2].arabic) \(months[parts[1] - 1]) \(parts[0].arabic)"
    }

    /// 12-hour clock: "07:00:00" → "٧:٠٠ صباحًا", "13:30" → "١:٣٠ مساءً", "00:15" → "١٢:١٥ صباحًا".
    static func time(_ iso: String?) -> String {
        guard let iso else { return "" }
        let parts = iso.prefix(5).split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return String(iso.prefix(5)).arabicDigits }
        let (h, m) = (parts[0], parts[1])
        let hour12 = h % 12 == 0 ? 12 : h % 12
        return "\(hour12.arabic):\(String(format: "%02d", m).arabicDigits) \(h < 12 ? "صباحًا" : "مساءً")"
    }

    /// wage_amount (agorot) → "٢٥٠ ₪ / يوم"
    static func wage(_ minor: Int, currency: String, basis: String) -> String {
        let sym = currency == "ILS" ? "₪" : currency
        let basisAr: String
        switch basis {
        case "PER_DAY": basisAr = "/ يوم"
        case "PER_HOUR": basisAr = "/ ساعة"
        case "PER_TASK": basisAr = "/ مهمة"
        default: basisAr = ""
        }
        return "\((minor / 100).arabic) \(sym) \(basisAr)".trimmingCharacters(in: .whitespaces)
    }

    static func basisWord(_ basis: String?) -> String {
        switch basis {
        case "PER_DAY": return "يومي"
        case "PER_HOUR": return "بالساعة"
        case "PER_TASK": return "بالمهمة"
        default: return basis ?? ""
        }
    }

    static func paymentMethod(_ method: String?) -> String {
        switch method {
        case "JAWWAL_PAY": return "جوال باي"
        case "PALPAY": return "بال باي"
        case "BANK_OF_PALESTINE": return "بنك فلسطين"
        default: return method ?? ""
        }
    }
}
