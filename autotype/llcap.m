#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <dlfcn.h>
#import <stdlib.h>
#import <math.h>

static CGImageRef (*ll_capture)(CGRect, uint32_t, uint32_t, uint32_t) = NULL;

static void load_capture(void) {
    if (!ll_capture) ll_capture = dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
}

static int roblox_window(void) {
    CFArrayRef info = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!info) return 0;
    int found = 0;
    double best = 0;
    for (CFIndex i = 0; i < CFArrayGetCount(info); i++) {
        CFDictionaryRef d = CFArrayGetValueAtIndex(info, i);
        CFStringRef owner = CFDictionaryGetValue(d, kCGWindowOwnerName);
        if (!owner) continue;
        BOOL player = CFStringCompare(owner, CFSTR("Roblox"), kCFCompareCaseInsensitive) == kCFCompareEqualTo
                   || CFStringCompare(owner, CFSTR("RobloxPlayer"), kCFCompareCaseInsensitive) == kCFCompareEqualTo
                   || CFStringCompare(owner, CFSTR("RobloxPlayerBeta"), kCFCompareCaseInsensitive) == kCFCompareEqualTo;
        if (!player) continue;
        int layer = 0, wid = 0;
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowLayer), kCFNumberIntType, &layer);
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowNumber), kCFNumberIntType, &wid);
        CGRect r = CGRectZero;
        CGRectMakeWithDictionaryRepresentation(CFDictionaryGetValue(d, kCGWindowBounds), &r);
        double area = r.size.width * r.size.height;
        if (layer == 0 && area > best && r.size.width > 200 && r.size.height > 200) {
            best = area;
            found = wid;
        }
    }
    CFRelease(info);
    return found;
}

int ll_grab(unsigned char **out, int *w, int *h) {
    if (out) *out = NULL;
    if (w) *w = 0;
    if (h) *h = 0;
    load_capture();
    if (!ll_capture) return 0;
    int wid = roblox_window();
    if (!wid) return 0;

    uint32_t options[] = {
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
    };
    CGImageRef img = NULL;
    for (int i = 0; i < 2 && !img; i++) {
        CGImageRef attempt = ll_capture(CGRectNull, kCGWindowListOptionIncludingWindow, (uint32_t)wid, options[i]);
        if (!attempt) continue;
        if (CGImageGetWidth(attempt) > 200 && CGImageGetHeight(attempt) > 200) {
            img = attempt;
            break;
        }
        CGImageRelease(attempt);
    }
    if (!img) return 0;
    size_t W = CGImageGetWidth(img);
    size_t H = CGImageGetHeight(img);

    if (W < 200 || H < 200 || W > 8000 || H > 8000) {
        CGImageRelease(img);
        return 0;
    }
    // Resize directly into a bounded capture buffer, instead of allocating
    // the full Retina screen and discarding every second/third pixel.
    double factor = fmax(1.0, fmax((double)W / 1600.0, (double)H / 1600.0));
    W = (size_t)((double)W / factor);
    H = (size_t)((double)H / factor);
    unsigned char *buf = calloc(W * H, 4);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = buf ? CGBitmapContextCreate(buf, W, H, 8, W * 4, cs, kCGImageAlphaPremultipliedLast) : NULL;
    CGColorSpaceRelease(cs);
    if (!ctx) {
        free(buf);
        CGImageRelease(img);
        return 0;
    }
    CGContextSetInterpolationQuality(ctx, kCGInterpolationHigh);
    CGContextDrawImage(ctx, CGRectMake(0, 0, W, H), img);
    CGContextRelease(ctx);
    CGImageRelease(img);

    *out = buf;
    *w = (int)W;
    *h = (int)H;
    return 1;
}
