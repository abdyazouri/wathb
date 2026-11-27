import SwiftUI

// MARK: - Buttons

struct PrimaryButtonStyle: ButtonStyle {
    var color: Color = Brand.primary
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.wathb(16, .medium))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(color.opacity(isEnabled ? (configuration.isPressed ? 0.8 : 1) : 0.4),
                        in: RoundedRectangle(cornerRadius: 12))
    }
}

struct OutlineButtonStyle: ButtonStyle {
    var color: Color = Brand.primary
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.wathb(16, .medium))
            .foregroundStyle(color.opacity(isEnabled ? 1 : 0.4))
            .frame(maxWidth: .infinity, minHeight: 46)
            .background(color.opacity(configuration.isPressed ? 0.08 : 0), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(color.opacity(isEnabled ? 0.7 : 0.3), lineWidth: 1))
    }
}

/// A primary button that shows a spinner while `loading`.
struct LoadingButton: View {
    let title: String
    var loading = false
    var color: Color = Brand.primary
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            if loading { ProgressView().tint(.white) } else { Text(title) }
        }
        .buttonStyle(PrimaryButtonStyle(color: color))
        .disabled(loading)
    }
}

// MARK: - Containers

struct CardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
            .shadow(color: .black.opacity(0.06), radius: 6, y: 2)
    }
}

extension View {
    func card() -> some View { modifier(CardModifier()) }
}

/// A coloured note inside a card (reminders, warnings, confirmations).
struct Note: View {
    let text: String
    var background: Color = Brand.successContainer
    var foreground: Color = .primary

    var body: some View {
        Text(text)
            .font(.wathb(14))
            .foregroundStyle(foreground)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct StatusBadge: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.wathb(12, .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
    }
}

/// "label  value" line used on job and task details.
struct DetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .top) {
            Text(label).foregroundStyle(Brand.muted).frame(maxWidth: .infinity, alignment: .leading)
            Text(value).frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.wathb(15))
    }
}

// MARK: - States

struct LoadingView: View {
    var body: some View {
        ProgressView().controlSize(.large).tint(Brand.primary)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct MessageView: View {
    let message: String
    var isError = false
    var retry: (() -> Void)?

    var body: some View {
        VStack(spacing: 16) {
            Text(message)
                .font(.wathb(16))
                .foregroundStyle(isError ? Brand.error : Brand.muted)
                .multilineTextAlignment(.center)
            if let retry {
                Button("إعادة المحاولة", action: retry).buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 220)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, minHeight: 320)
    }
}

// MARK: - Fields

struct FormField: View {
    let label: String
    @Binding var text: String
    var keyboard: UIKeyboardType = .default
    var contentType: UITextContentType?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.wathb(14, .medium)).foregroundStyle(Brand.muted)
            TextField("", text: $text)
                .font(.wathb(17))
                .keyboardType(keyboard)
                .textContentType(contentType)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .fieldBox()
        }
    }
}

/// Password with the «إظهار كلمة المرور» eye, like the Android screens.
struct PasswordField: View {
    var label = "كلمة المرور"
    @Binding var text: String
    var contentType: UITextContentType = .password
    @State private var visible = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.wathb(14, .medium)).foregroundStyle(Brand.muted)
            HStack {
                Group {
                    if visible { TextField("", text: $text) } else { SecureField("", text: $text) }
                }
                .font(.wathb(17))
                .textContentType(contentType)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                Button { visible.toggle() } label: {
                    Image(systemName: visible ? "eye.slash" : "eye").foregroundStyle(Brand.muted)
                }
                .accessibilityLabel(visible ? "إخفاء كلمة المرور" : "إظهار كلمة المرور")
            }
            .fieldBox()
        }
    }
}

extension View {
    func fieldBox() -> some View {
        padding(.horizontal, 14).frame(minHeight: 50)
            .background(Brand.field, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.border, lineWidth: 1))
    }
}

// MARK: - Toast

/// A short message at the bottom of the screen (the Android snackbar).
struct ToastModifier: ViewModifier {
    @Binding var message: String?

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            if let message {
                Text(message)
                    .font(.wathb(15))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.leading)
                    .padding(.horizontal, 16).padding(.vertical, 12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(hex: 0x313033), in: RoundedRectangle(cornerRadius: 12))
                    .padding(.horizontal, 16).padding(.bottom, 12)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .onTapGesture { self.message = nil }
                    .task(id: message) {
                        try? await Task.sleep(for: .seconds(4))
                        withAnimation { self.message = nil }
                    }
            }
        }
        .animation(.easeInOut(duration: 0.2), value: message)
    }
}

extension View {
    func toast(_ message: Binding<String?>) -> some View { modifier(ToastModifier(message: message)) }
}

// MARK: - Support

struct SupportWhatsappButton: View {
    @Environment(\.openURL) private var openURL
    private var session: Session { .shared }

    var body: some View {
        let digits = session.supportWhatsapp.filter { $0.isNumber }
        if !digits.isEmpty, let url = URL(string: "https://wa.me/\(digits)") {
            Button { openURL(url) } label: {
                Label("تواصل مع الدعم", systemImage: "headphones")
            }
            .buttonStyle(PrimaryButtonStyle(color: Brand.secondary))
        }
    }
}

// MARK: - Contact links

enum Contact {
    static func call(_ phone: String) -> URL? { URL(string: "tel:\(phone.localPhone)") }
    static func whatsapp(_ phone: String) -> URL? { URL(string: "https://wa.me/\(phone.filter { $0.isNumber })") }
}
