import Foundation
import Vision
let image = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
try VNImageRequestHandler(url: image).perform([request])
for result in request.results ?? [] {
    print(result.topCandidates(1).first?.string ?? "")
}
