// Image-only lightbar contour refinement v3: measured color, complete pair, adaptive search coverage. No target geometry/state input.
// Replaces only the disabled corners_optimizor translation unit when explicitly
// selected by a newly identified native build. Recovered sources are preserved.
#include "utility/math/corners_optimizor.hpp"
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <optional>
#include <vector>

namespace rmcs::util {
namespace {
struct BarFit { cv::Point2d upper, lower; double length; };
constexpr double kMinColorDifference = 24.0;
constexpr double kMinColorBrightness = 64.0;
constexpr double kMaxAxisAngleRadians = 0.4363323129985824; // 25 degrees
constexpr double kMaxPairAngleRadians = 0.2617993877991494; // 15 degrees

std::optional<BarFit> fit_bar(const cv::Mat& image, const Lightbar2d& bar, int expansion=0) {
    if (image.empty() || image.type() != CV_8UC3 ||
        (bar.color != ArmorColor::BLUE && bar.color != ArmorColor::RED)) return {};
    cv::Point2d upper(bar.upper.x, bar.upper.y), lower(bar.lower.x, bar.lower.y);
    const auto predicted_length = cv::norm(lower - upper);
    if (!std::isfinite(predicted_length) || predicted_length < 4.) return {};
    const auto center = (upper + lower) * .5;
    const auto direction = (lower - upper) / predicted_length;
    const auto normal = cv::Point2d(-direction.y, direction.x);
    const auto half_length = std::max(8., .95 * predicted_length);
    const auto half_width = std::max(4., .25 * predicted_length) * (expansion ? 2. : 1.);
    const auto x_extent = std::abs(direction.x) * half_length + std::abs(normal.x) * half_width;
    const auto y_extent = std::abs(direction.y) * half_length + std::abs(normal.y) * half_width;
    const auto roi = cv::Rect(cv::Point(int(std::floor(center.x-x_extent)), int(std::floor(center.y-y_extent))),
        cv::Point(int(std::ceil(center.x+x_extent))+1, int(std::ceil(center.y+y_extent))+1)) &
        cv::Rect(0, 0, image.cols, image.rows);
    if (roi.width < 3 || roi.height < 3) return {};
    cv::Mat mask = cv::Mat::zeros(roi.size(), CV_8U);
    for (int y=0;y<roi.height;++y) for (int x=0;x<roi.width;++x) {
        const auto pixel = image.at<cv::Vec3b>(roi.y+y, roi.x+x);
        const int primary = pixel[bar.color==ArmorColor::BLUE ? 0 : 2];
        const int opposite = pixel[bar.color==ArmorColor::BLUE ? 2 : 0];
        if (primary >= kMinColorBrightness && primary-std::max<int>(opposite,pixel[1]) >= kMinColorDifference)
            mask.at<unsigned char>(y,x)=255;
    }
    // Fill one-pixel holes from lens interpolation; never synthesize endpoints.
    cv::morphologyEx(mask, mask, cv::MORPH_CLOSE, cv::Mat::ones(3,3,CV_8U));
    cv::Mat labels, stats, centroids;
    const int count = cv::connectedComponentsWithStats(mask,labels,stats,centroids,8,CV_32S);
    std::optional<BarFit> best;
    bool measured_lateral_boundary=false;
    double best_cost = 1e100;
    for (int label=1;label<count;++label) {
        if (stats.at<int>(label,cv::CC_STAT_AREA) < std::max(4., predicted_length*.6)) continue;
        const int bx=stats.at<int>(label,cv::CC_STAT_LEFT), by=stats.at<int>(label,cv::CC_STAT_TOP);
        const int bw=stats.at<int>(label,cv::CC_STAT_WIDTH), bh=stats.at<int>(label,cv::CC_STAT_HEIGHT);
        // An endpoint touching a search/sensor boundary is not a measured edge.
        if (by==0 || by+bh==roi.height) continue;
        if (bx==0 || bx+bw==roi.width) {measured_lateral_boundary=true;continue;}
        std::vector<cv::Point2d> support;
        for(int y=by;y<by+bh;++y)for(int x=bx;x<bx+bw;++x)
            if(labels.at<int>(y,x)==label) support.emplace_back(x+roi.x,y+roi.y);
        cv::Mat points(support); points=points.reshape(1);
        const cv::PCA pca(points,cv::Mat(),cv::PCA::DATA_AS_ROW);
        cv::Point2d axis(pca.eigenvectors.at<double>(0,0),pca.eigenvectors.at<double>(0,1));
        if(axis.dot(direction)<0.)axis=-axis;
        if(axis.dot(direction)<std::cos(kMaxAxisAngleRadians))continue;
        const cv::Point2d cross(-axis.y,axis.x);
        cv::Point2d mean(pca.mean.at<double>(0,0),pca.mean.at<double>(0,1));
        double amin=1e100,amax=-1e100,nmin=1e100,nmax=-1e100;
        for(const auto& point:support){auto p=point-mean;auto a=p.dot(axis),n=p.dot(cross);
            amin=std::min(amin,a);amax=std::max(amax,a);nmin=std::min(nmin,n);nmax=std::max(nmax,n);}
        const double length=amax-amin+1., width=nmax-nmin+1.;
        if(length<.65*predicted_length || length>1.9*predicted_length || length/std::max(width,1.)<2.5)continue;
        const auto distance=cv::norm(mean-center);
        if(distance>.45*predicted_length)continue;
        const double cost=distance/predicted_length + width/length;
        if(cost>=best_cost)continue;
        best=BarFit{mean+axis*(amin-.5),mean+axis*(amax+.5),length};best_cost=cost;
    }
    // Expand once only when actual colored support proves search truncation.
    // Full sensor/longitudinal clipping remains rejected; no endpoint invented.
    if(!best && measured_lateral_boundary && expansion==0)return fit_bar(image,bar,1);
    return best;
}
}

auto optimize_corners(const cv::Mat& image, Lightbar2d& bar) -> void {
    if(auto fit=fit_bar(image,bar)) {
        bar.upper=Point2d{fit->upper.x,fit->upper.y};
        bar.lower=Point2d{fit->lower.x,fit->lower.y};
    }
}

auto optimize_corners(const cv::Mat& image, Armor2ds& armors) -> void {
    // Do not let inferred corners behind an occluder create a physical pose.
    // Both bars require complete actual colored-pixel support. Model class and
    // confidence are retained; DARK color is resolved only from a unique
    // measured same-color pair, without own team/target state inputs.
    std::erase_if(armors,[&](Armor2d& armor) {
        struct Pair {BarFit left,right;ArmorColor color;};
        auto pair_for=[&](ArmorColor color)->std::optional<Pair>{
            Lightbar2d left{.color=color,.upper=Point2d{armor.tl.x,armor.tl.y},.lower=Point2d{armor.bl.x,armor.bl.y}};
            Lightbar2d right{.color=color,.upper=Point2d{armor.tr.x,armor.tr.y},.lower=Point2d{armor.br.x,armor.br.y}};
            auto l=fit_bar(image,left),r=fit_bar(image,right);
            if(!l || !r)return {};
            if(std::max(l->length,r->length)/std::min(l->length,r->length)>1.25)return {};
            const auto la=(l->lower-l->upper)/cv::norm(l->lower-l->upper);
            const auto ra=(r->lower-r->upper)/cv::norm(r->lower-r->upper);
            if(la.dot(ra)<std::cos(kMaxPairAngleRadians))return {};
            if((l->upper.x+l->lower.x)>=(r->upper.x+r->lower.x))return {};
            return Pair{*l,*r,color};
        };
        std::optional<Pair> pair;
        if(armor.color==ArmorColor::BLUE || armor.color==ArmorColor::RED)pair=pair_for(armor.color);
        else if(armor.color==ArmorColor::DARK){
            auto blue=pair_for(ArmorColor::BLUE),red=pair_for(ArmorColor::RED);
            if(bool(blue)==bool(red))return true; // None or ambiguous colors.
            pair=blue?blue:red;
        }
        if(!pair)return true;
        armor.color=pair->color;
        armor.tl=cv::Point2f(pair->left.upper);armor.bl=cv::Point2f(pair->left.lower);
        armor.tr=cv::Point2f(pair->right.upper);armor.br=cv::Point2f(pair->right.lower);
        armor.center=(armor.tl+armor.bl+armor.br+armor.tr)*.25f;
        return false;
    });
}
}
