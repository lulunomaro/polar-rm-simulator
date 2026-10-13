#pragma once

#include <Eigen/Cholesky>
#include <Eigen/Eigenvalues>
#include <cmath>
#include <limits>
#include <optional>
#include <span>

namespace rmcs::util {

inline auto association_prior_eligible(std::size_t update_count, bool last_correction_consistent) noexcept -> bool {
    return update_count >= 10 && last_correction_consistent;
}

struct AssociationTrialScore {
    double fit = std::numeric_limits<double>::infinity();
    double motion = std::numeric_limits<double>::infinity();
};

inline auto valid_association_score(const AssociationTrialScore& score) noexcept -> bool {
    return std::isfinite(score.fit) && score.fit >= 0.0
        && std::isfinite(score.motion) && score.motion >= 0.0;
}

inline auto association_dominates(
    const AssociationTrialScore& a, const AssociationTrialScore& b) noexcept -> bool {
    return valid_association_score(a) && valid_association_score(b)
        && a.fit < b.fit && a.motion < b.motion;
}

// Slot zero is the unchanged original association. A tradeoff or tie abstains.
inline auto unique_association_dominator(std::span<const AssociationTrialScore> scores) noexcept
    -> std::optional<std::size_t> {
    if (scores.empty() || !valid_association_score(scores.front())) return std::nullopt;
    for (std::size_t i = 1; i < scores.size(); ++i) {
        if (!association_dominates(scores[i], scores.front())) continue;
        bool unique = true;
        for (std::size_t j = 1; j < scores.size(); ++j) {
            if (j == i || !association_dominates(scores[j], scores.front())) continue;
            if (!association_dominates(scores[i], scores[j])) { unique = false; break; }
        }
        if (unique) return i;
    }
    return std::nullopt;
}

inline auto valid_association_projection(const Eigen::Vector3d& upper_camera,
    const Eigen::Vector3d& lower_camera, const Eigen::Vector2d& upper_pixel,
    const Eigen::Vector2d& lower_pixel) noexcept -> bool {
    return upper_camera.allFinite() && lower_camera.allFinite()
        && upper_camera.x() > 0.0 && lower_camera.x() > 0.0
        && upper_pixel.allFinite() && lower_pixel.allFinite();
}

inline auto valid_association_covariance(
    const Eigen::Matrix<double, 11, 11>& covariance) noexcept -> bool {
    if (!covariance.allFinite()) return false;
    const double numerical_tolerance = 11.0 * std::numeric_limits<double>::epsilon();
    const double scale = covariance.cwiseAbs().maxCoeff();
    if ((covariance - covariance.transpose()).cwiseAbs().maxCoeff()
        > numerical_tolerance * scale) return false;
    const Eigen::Matrix<double, 11, 11> symmetric = 0.5 * (covariance + covariance.transpose());
    const Eigen::SelfAdjointEigenSolver<Eigen::Matrix<double, 11, 11>> spectrum(
        symmetric, Eigen::EigenvaluesOnly);
    return spectrum.info() == Eigen::Success && spectrum.eigenvalues().allFinite()
        && spectrum.eigenvalues()[0] > numerical_tolerance * spectrum.eigenvalues()[10];
}

inline auto association_motion_cost(const Eigen::Matrix<double, 11, 1>& prior,
    const Eigen::Matrix<double, 11, 1>& posterior,
    const Eigen::Matrix<double, 11, 11>& covariance) noexcept -> std::optional<double> {
    if (!prior.allFinite() || !posterior.allFinite() || !covariance.allFinite())
        return std::nullopt;
    if (!valid_association_covariance(covariance)) return std::nullopt;
    const Eigen::Matrix<double, 11, 11> symmetric = 0.5 * (covariance + covariance.transpose());
    const Eigen::LLT<Eigen::Matrix<double, 11, 11>> factor(symmetric);
    if (factor.info() != Eigen::Success) return std::nullopt;
    Eigen::Matrix<double, 11, 1> delta = posterior - prior;
    delta[6] = std::atan2(std::sin(delta[6]), std::cos(delta[6]));
    const Eigen::Matrix<double, 11, 1> solution = factor.solve(delta);
    if (!solution.allFinite()) return std::nullopt;
    const double cost = delta.dot(solution);
    if (!std::isfinite(cost) || cost < 0.0) return std::nullopt;
    return cost;
}

}
