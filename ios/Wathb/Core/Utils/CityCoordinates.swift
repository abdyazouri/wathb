import CoreLocation

/// Approximate city centres (android ui/utils/LocationUtils.kt); jobs carry a city, not coordinates.
enum CityCoordinates {
    private static let coords: [(String, Double, Double)] = [
        ("غزة", 31.5017, 34.4668), ("مدينة غزة", 31.5017, 34.4668),
        ("خانيونس", 31.3428, 34.3064), ("خان يونس", 31.3428, 34.3064),
        ("رفح", 31.2912, 34.2498), ("جباليا", 31.5279, 34.4913), ("جبالية", 31.5279, 34.4913),
        ("دير البلح", 31.4176, 34.3478), ("بيت لاهيا", 31.5543, 34.5003), ("بيت حانون", 31.5381, 34.5320),
        ("النصيرات", 31.4390, 34.3710), ("البريج", 31.4560, 34.3793), ("المغازي", 31.4640, 34.3680),
        ("رام الله", 31.9038, 35.2034), ("القدس", 31.7683, 35.2137), ("الخليل", 31.5326, 35.0998),
        ("نابلس", 32.2211, 35.2544), ("جنين", 32.4633, 35.2962), ("طولكرم", 32.3100, 35.0289),
        ("قلقيلية", 32.1876, 34.9704), ("بيت لحم", 31.7054, 35.2024), ("أريحا", 31.8579, 35.4612),
        ("طوباس", 32.3205, 35.3677), ("سلفيت", 32.0842, 35.1829),
    ]

    static func of(_ city: String) -> CLLocationCoordinate2D {
        if let c = coords.first(where: { $0.0 == city }) { return .init(latitude: c.1, longitude: c.2) }
        if let c = coords.first(where: { city.contains($0.0) || $0.0.contains(city) }) {
            return .init(latitude: c.1, longitude: c.2)
        }
        return .init(latitude: 31.5017, longitude: 34.4668)  // central Gaza
    }
}
