import Foundation

/// Swift representation of a custom Voxa work mode.
struct VoxaMode: Codable, Identifiable, Hashable {
    var id: String { name }
    let name: String
    let trigger: String
    let description: String
    let instructions: [String]
    let created_at: String?
    let updated_at: String?

    enum CodingKeys: String, CodingKey {
        case name
        case trigger
        case description
        case instructions
        case created_at
        case updated_at
    }
}
