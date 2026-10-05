#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <dlfcn.h>
#import <math.h>
#import <stdint.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <unistd.h>

// Reads the Last Letter board from the Roblox window.
// Letter tiles are matched against fonts locally, so a frame stays fast
// and a single tile still resolves. Vision is only used for the turn line,
// and only when that line's pixels actually change.

static CGImageRef (*ll_capture)(CGRect, uint32_t, uint32_t, uint32_t) = NULL;

static const int GRID = 24;
static const int CELLS = 24 * 24;
static const int MAX_FONTS = 8;
static float templates[8][26][576];
static int template_count = 0;

static int roblox_window(void) {
    CFArrayRef info = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!info) return 0;
    int found = 0;
    double best = 0;
    CFIndex n = CFArrayGetCount(info);
    for (CFIndex i = 0; i < n; i++) {
        CFDictionaryRef d = CFArrayGetValueAtIndex(info, i);
        CFStringRef owner = CFDictionaryGetValue(d, kCGWindowOwnerName);
        if (!owner) continue;
        if (CFStringFind(owner, CFSTR("Roblox"), kCFCompareCaseInsensitive).location == kCFNotFound) continue;
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

static CGImageRef capture(int wid) {
    if (!ll_capture || !wid) return NULL;
    return ll_capture(CGRectNull, kCGWindowListOptionIncludingWindow, (uint32_t)wid,
                      kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution);
}

static int dark_px(const unsigned char *p) {
    // Anti-aliased edges sit above a hard black. Counting them keeps thin letters.
    return p[0] < 150 && p[1] < 150 && p[2] < 150;
}

static int white_px(const unsigned char *p) {
    int hi = p[0] > p[1] ? p[0] : p[1];
    if (p[2] > hi) hi = p[2];
    int lo = p[0] < p[1] ? p[0] : p[1];
    if (p[2] < lo) lo = p[2];
    return lo > 198 && hi - lo < 40;
}

static void density_from(const unsigned char *buf, int w, int h, float *g) {
    memset(g, 0, sizeof(float) * CELLS);
    int minx = w, miny = h, maxx = -1, maxy = -1;
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            if (!dark_px(buf + ((size_t)y * w + x) * 4)) continue;
            if (x < minx) minx = x;
            if (x > maxx) maxx = x;
            if (y < miny) miny = y;
            if (y > maxy) maxy = y;
        }
    }
    if (maxx < minx) return;
    int bw = maxx - minx + 1, bh = maxy - miny + 1;
    int side = bw > bh ? bw : bh;
    int ox = minx - (side - bw) / 2;
    int oy = miny - (side - bh) / 2;
    for (int gy = 0; gy < GRID; gy++) {
        for (int gx = 0; gx < GRID; gx++) {
            int sx = ox + gx * side / GRID;
            int sy = oy + gy * side / GRID;
            int sx1 = ox + (gx + 1) * side / GRID;
            int sy1 = oy + (gy + 1) * side / GRID;
            if (sx1 <= sx) sx1 = sx + 1;
            if (sy1 <= sy) sy1 = sy + 1;
            int ink = 0, tot = 0;
            for (int y = sy; y < sy1; y++) {
                for (int x = sx; x < sx1; x++) {
                    if (x < 0 || y < 0 || x >= w || y >= h) continue;
                    tot++;
                    if (dark_px(buf + ((size_t)y * w + x) * 4)) ink++;
                }
            }
            g[gy * GRID + gx] = tot ? (float)ink / (float)tot : 0;
        }
    }
}

static float cosine(const float *a, const float *b) {
    double dot = 0, na = 0, nb = 0;
    for (int i = 0; i < CELLS; i++) {
        dot += (double)a[i] * b[i];
        na += (double)a[i] * a[i];
        nb += (double)b[i] * b[i];
    }
    if (na < 1e-6 || nb < 1e-6) return 0;
    return (float)(dot / (sqrt(na) * sqrt(nb)));
}

static void render_template(NSFont *font, unichar ch, float *g) {
    if (!font) {
        memset(g, 0, sizeof(float) * CELLS);
        return;
    }
    NSString *s = [NSString stringWithCharacters:&ch length:1];
    NSDictionary *attr = @{
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: NSColor.blackColor
    };
    NSSize sz = [s sizeWithAttributes:attr];
    int tw = (int)ceil(sz.width) + 48;
    int th = (int)ceil(sz.height) + 48;
    unsigned char *tb = calloc((size_t)tw * th * 4, 1);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(tb, tw, th, 8, tw * 4, cs, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(cs);
    if (ctx) {
        CGContextSetRGBFillColor(ctx, 1, 1, 1, 1);
        CGContextFillRect(ctx, CGRectMake(0, 0, tw, th));
        NSGraphicsContext *gc = [NSGraphicsContext graphicsContextWithCGContext:ctx flipped:NO];
        [NSGraphicsContext saveGraphicsState];
        [NSGraphicsContext setCurrentContext:gc];
        [s drawAtPoint:NSMakePoint(24, 20) withAttributes:attr];
        [NSGraphicsContext restoreGraphicsState];
        CGContextRelease(ctx);
        density_from(tb, tw, th, g);
    }
    free(tb);
}

static void add_font(NSFont *font, BOOL lower) {
    if (!font || template_count >= MAX_FONTS) return;
    unichar base = lower ? 'a' : 'A';
    for (int i = 0; i < 26; i++) {
        render_template(font, (unichar)(base + i), templates[template_count][i]);
    }
    template_count++;
}

static void build_templates(void) {
    template_count = 0;
    NSFont *faces[] = {
        [NSFont boldSystemFontOfSize:180],
        [NSFont fontWithName:@"GillSans-SemiBold" size:180],
        [NSFont fontWithName:@"Avenir-Heavy" size:180],
        [NSFont fontWithName:@"Arial-BoldMT" size:180],
        [NSFont fontWithName:@"ArialRoundedMTBold" size:180],
    };
    for (int i = 0; i < (int)(sizeof(faces) / sizeof(faces[0])); i++) {
        if (!faces[i]) continue;
        NSFont *font = [NSFont fontWithName:faces[i].fontName size:180] ?: faces[i];
        add_font(font, NO);
        add_font(font, YES);
        if (template_count >= MAX_FONTS) break;
    }
}

static char classify(const unsigned char *buf, int w, int h, float *outScore, float *outMargin) {
    float tile[576];
    density_from(buf, w, h, tile);
    float best = 0, second = 0;
    int bestI = 0;
    for (int f = 0; f < template_count; f++) {
        float top = -1, next = -1;
        int topI = 0;
        for (int i = 0; i < 26; i++) {
            float c = cosine(tile, templates[f][i]);
            if (c > top) {
                next = top;
                top = c;
                topI = i;
            } else if (c > next) {
                next = c;
            }
        }
        if (top > best) {
            best = top;
            second = next;
            bestI = topI;
        }
    }
    if (outScore) *outScore = best;
    if (outMargin) *outMargin = best - second;
    if (getenv("LLDEBUG")) {
        fprintf(stderr, "class %c %.3f  margin %.3f\n", 'a' + bestI, best, best - second);
    }
    if (best <= 0) return 0;
    return (char)('a' + bestI);
}

static NSString *ocr_text(CGImageRef cg, BOOL accurate) {
    if (!cg) return @"";
    __block NSMutableString *text = [NSMutableString string];
    VNRecognizeTextRequest *req = [[VNRecognizeTextRequest alloc] initWithCompletionHandler:^(VNRequest *request, NSError *error) {
        if (error) return;
        NSArray *obs = request.results;
        NSMutableArray *rows = [NSMutableArray arrayWithArray:obs];
        [rows sortUsingComparator:^NSComparisonResult(VNRecognizedTextObservation *a, VNRecognizedTextObservation *b) {
            CGFloat ay = a.boundingBox.origin.y;
            CGFloat by = b.boundingBox.origin.y;
            if (ay > by + 0.02) return NSOrderedAscending;
            if (by > ay + 0.02) return NSOrderedDescending;
            return a.boundingBox.origin.x < b.boundingBox.origin.x ? NSOrderedAscending : NSOrderedDescending;
        }];
        for (VNRecognizedTextObservation *o in rows) {
            VNRecognizedText *top = [[o topCandidates:1] firstObject];
            if (!top.string.length || top.confidence < 0.2) continue;
            if (text.length) [text appendString:@" "];
            [text appendString:top.string];
        }
    }];
    req.recognitionLevel = accurate ? VNRequestTextRecognitionLevelAccurate : VNRequestTextRecognitionLevelFast;
    req.usesLanguageCorrection = NO;
    req.recognitionLanguages = @[@"en-US"];
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:cg options:@{}];
    [handler performRequests:@[req] error:nil];
    return text;
}

static CGImageRef crop_image(CGImageRef src, int x, int y, int w, int h) {
    if (w < 2 || h < 2) return NULL;
    size_t iw = CGImageGetWidth(src), ih = CGImageGetHeight(src);
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x + w > (int)iw) w = (int)iw - x;
    if (y + h > (int)ih) h = (int)ih - y;
    if (w < 2 || h < 2) return NULL;
    return CGImageCreateWithImageInRect(src, CGRectMake(x, y, w, h));
}

static CGImageRef fit_width(CGImageRef src, int maxW) {
    size_t w = CGImageGetWidth(src), h = CGImageGetHeight(src);
    if ((int)w <= maxW) return CGImageRetain(src);
    size_t nw = (size_t)maxW;
    size_t nh = h * nw / w;
    if (nh < 2) nh = 2;
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(NULL, nw, nh, 8, nw * 4, cs, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(cs);
    if (!ctx) return CGImageRetain(src);
    CGContextSetInterpolationQuality(ctx, kCGInterpolationMedium);
    CGContextDrawImage(ctx, CGRectMake(0, 0, nw, nh), src);
    CGImageRef out = CGBitmapContextCreateImage(ctx);
    CGContextRelease(ctx);
    return out;
}

typedef struct {
    int x, y, w, h;
} Box;

static int box_cmp(const void *a, const void *b) {
    const Box *ba = a, *bb = b;
    return ba->x - bb->x;
}

static int contained(Box inner, Box outer) {
    int cx = inner.x + inner.w / 2;
    int cy = inner.y + inner.h / 2;
    return cx > outer.x && cy > outer.y && cx < outer.x + outer.w && cy < outer.y + outer.h
        && inner.w * inner.h < outer.w * outer.h;
}

static NSString *clean_field(NSString *text) {
    if (!text.length) return @"";
    return [[text stringByReplacingOccurrencesOfString:@"\t" withString:@" "]
        stringByReplacingOccurrencesOfString:@"\n" withString:@" "];
}

static void emit(NSString *prompt, NSString *header, int tiles, int ms, int full, NSString *error) {
    NSString *p = prompt.length ? prompt : @"-";
    printf("PROMPT\t%s\tHEADER\t%s\tTILES\t%d\tMS\t%d\tFULL\t%d\tERROR\t%s\n",
           p.UTF8String, clean_field(header).UTF8String, tiles, ms, full, clean_field(error).UTF8String);
    fflush(stdout);
}

static unsigned long hash_bytes(const unsigned char *buf, int w, int h, int stride) {
    unsigned long hash = 1469598103934665603UL;
    if (stride < 1) stride = 1;
    for (int y = 0; y < h; y += stride) {
        const unsigned char *row = buf + (size_t)y * w * 4;
        for (int x = 0; x < w; x += stride) {
            hash ^= row[x * 4];
            hash *= 1099511628211UL;
        }
    }
    return hash;
}

static void scan_image(CGImageRef img);

static void one_frame(int wid) {
    CGImageRef img = capture(wid);
    if (!img) {
        emit(@"", @"", 0, 0, 0, @"");
        return;
    }
    scan_image(img);
}

static CGImageRef image_from_buffer(const unsigned char *buf, size_t W, size_t H) {
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGDataProviderRef provider = CGDataProviderCreateWithData(NULL, buf, W * H * 4, NULL);
    CGImageRef image = CGImageCreate(
        W, H, 8, 32, W * 4, cs, kCGImageAlphaPremultipliedLast, provider, NULL, false,
        kCGRenderingIntentDefault);
    CGDataProviderRelease(provider);
    CGColorSpaceRelease(cs);
    return image;
}

static unsigned long hash_tile(const unsigned char *buf, size_t W, Box box) {
    unsigned long hash = 1469598103934665603UL;
    for (int y = box.y; y < box.y + box.h; y += 4) {
        const unsigned char *line = buf + (size_t)y * W * 4 + (size_t)box.x * 4;
        for (int x = 0; x < box.w; x += 4) {
            hash ^= line[x * 4];
            hash *= 1099511628211UL;
        }
    }
    return hash;
}

static char looks_like_i(const unsigned char *buf, size_t W, size_t H, Box box);

static char ocr_one_tile(const unsigned char *buf, size_t W, size_t H, Box box) {
    // Keep the whole glyph. A deep crop clips M and W and the letter is dropped.
    int inset = box.w / 12;
    if (inset < 1) inset = 1;
    int sw = box.w - inset * 2;
    int sh = box.h - inset * 2;
    if (sw < 8 || sh < 8) return 0;
    int canvasSide = 180;
    unsigned char *canvas = calloc((size_t)canvasSide * canvasSide, 4);
    if (!canvas) return 0;
    for (size_t i = 0; i < (size_t)canvasSide * canvasSide; i++) {
        canvas[i * 4] = canvas[i * 4 + 1] = canvas[i * 4 + 2] = 255;
        canvas[i * 4 + 3] = 255;
    }
    for (int y = 0; y < canvasSide; y++) {
        int sy = box.y + inset + y * sh / canvasSide;
        if (sy < 0 || sy >= (int)H) continue;
        for (int x = 0; x < canvasSide; x++) {
            int sx = box.x + inset + x * sw / canvasSide;
            if (sx < 0 || sx >= (int)W) continue;
            unsigned char *s = (unsigned char *)buf + ((size_t)sy * W + sx) * 4;
            unsigned char *d = canvas + ((size_t)y * canvasSide + x) * 4;
            d[0] = s[0];
            d[1] = s[1];
            d[2] = s[2];
            d[3] = 255;
        }
    }
    CGImageRef image = image_from_buffer(canvas, (size_t)canvasSide, (size_t)canvasSide);
    NSString *text = ocr_text(image, NO) ?: @"";
    if (image) CGImageRelease(image);
    free(canvas);
    unichar found = 0;
    int count = 0;
    NSString *lower = text.lowercaseString;
    for (NSUInteger i = 0; i < lower.length; i++) {
        unichar ch = [lower characterAtIndex:i];
        if (ch < 'a' || ch > 'z') continue;
        found = ch;
        count++;
    }
    if (getenv("LLDEBUG")) fprintf(stderr, "tile [%s] -> %d\n", text.UTF8String ?: "", count);
    if (count == 1) return (char)found;
    return looks_like_i(buf, W, H, box) ? 'i' : 0;
}

// A capital I is a narrow bar down the middle of the tile. Vision often skips it.
static char looks_like_i(const unsigned char *buf, size_t W, size_t H, Box box) {
    int inset = box.w / 7;
    if (inset < 1) inset = 1;
    int minx = box.w, maxx = -1, miny = box.h, maxy = -1, ink = 0;
    for (int y = inset; y < box.h - inset; y++) {
        int sy = box.y + y;
        if (sy < 0 || sy >= (int)H) continue;
        for (int x = inset; x < box.w - inset; x++) {
            int sx = box.x + x;
            if (sx < 0 || sx >= (int)W) continue;
            if (!dark_px(buf + ((size_t)sy * W + sx) * 4)) continue;
            ink++;
            if (x < minx) minx = x;
            if (x > maxx) maxx = x;
            if (y < miny) miny = y;
            if (y > maxy) maxy = y;
        }
    }
    if (ink < 8 || maxx < minx) return 0;
    int bw = maxx - minx + 1;
    int bh = maxy - miny + 1;
    if (bh < box.h / 3 || bw * 3 > bh) return 0;
    int mid = (minx + maxx) / 2;
    if (abs(mid - box.w / 2) > box.w / 5) return 0;
    return 1;
}

// A round o is centered along its bottom edge. q puts a tail or a descender
// there, so those pixels sit to the right. Template scores treat the two bowls
// as the same letter, so this runs even when the score is high.
static char settle_qo(const unsigned char *buf, int w, int h, char guess) {
    if (guess != 'o' && guess != 'q') return guess;
    if (w < 8 || h < 8) return guess;
    int minx = w, miny = h, maxx = -1, maxy = -1;
    for (int y = 0; y < h; y++) {
        const unsigned char *row = buf + (size_t)y * w * 4;
        for (int x = 0; x < w; x++) {
            if (!dark_px(row + x * 4)) continue;
            if (x < minx) minx = x;
            if (x > maxx) maxx = x;
            if (y < miny) miny = y;
            if (y > maxy) maxy = y;
        }
    }
    if (maxx < minx) return guess;
    int bw = maxx - minx + 1;
    int bh = maxy - miny + 1;
    if (bw < 8 || bh < 8) return guess;
    int need = bh / 10;
    if (need < 2) need = 2;
    int got = 0, total = 0;
    double acc = 0;
    for (int y = maxy; y >= miny; y--) {
        const unsigned char *row = buf + (size_t)y * w * 4;
        int count = 0, summed = 0;
        for (int x = minx; x <= maxx; x++) {
            if (!dark_px(row + x * 4)) continue;
            count++;
            summed += x;
        }
        if (!count) continue;
        got++;
        total += count;
        acc += summed;
        if (got >= need) break;
    }
    if (total < 3) return guess;
    float rel = (float)((acc / (double)total) - minx) / (float)bw;
    if (rel >= 0.54f) return 'q';
    if (rel <= 0.53f) return 'o';
    return guess;
}

static char read_letter(const unsigned char *buf, size_t W, size_t H, Box box) {
    int w = box.w, h = box.h;
    if (w < 8 || h < 8 || w > 500 || h > 500) return 0;
    if (box.x < 0 || box.y < 0 || box.x + w > (int)W || box.y + h > (int)H) return 0;
    unsigned char *tile = malloc((size_t)w * h * 4);
    if (!tile) return 0;
    for (int y = 0; y < h; y++) {
        memcpy(tile + (size_t)y * w * 4,
               buf + ((size_t)(box.y + y) * W + (size_t)box.x) * 4,
               (size_t)w * 4);
    }
    float score = 0, margin = 0;
    char shaped = classify(tile, w, h, &score, &margin);
    if (shaped == 'o' || shaped == 'q') {
        shaped = settle_qo(tile, w, h, shaped);
        free(tile);
        if (score >= 0.62f) return shaped;
        char seen = ocr_one_tile(buf, W, H, box);
        if (seen && seen != 'o' && seen != 'q') return seen;
        return shaped;
    }
    free(tile);
    // A near-perfect template hit can skip OCR. Anything less was calling Y a W.
    if (shaped && score >= 0.94f && margin >= 0.08f) return shaped;
    char seen = ocr_one_tile(buf, W, H, box);
    if (seen) return seen;
    if (looks_like_i(buf, W, H, box)) return 'i';
    return 0;
}

static NSString *read_tiles(const unsigned char *buf, size_t W, size_t H, Box *row, int nrow) {
    static unsigned long seenHash[256];
    static char seenLetter[256];
    static int seenCount = 0;
    NSMutableString *letters = [NSMutableString string];
    for (int i = 0; i < nrow; i++) {
        unsigned long hash = hash_tile(buf, W, row[i]);
        char ch = 0;
        int known = 0;
        for (int k = 0; k < seenCount; k++) {
            if (seenHash[k] == hash) {
                ch = seenLetter[k];
                known = 1;
                break;
            }
        }
        if (!known) {
            ch = read_letter(buf, W, H, row[i]);
            // Don't remember a miss. A blurred frame was getting stuck as the letter.
            if (ch && seenCount < 256) {
                seenHash[seenCount] = hash;
                seenLetter[seenCount] = ch;
                seenCount++;
            }
        }
        // A missed tile is not a shorter word. The caller keeps the last complete read.
        if (!ch) return @"";
        [letters appendFormat:@"%c", ch];
    }
    if ((int)letters.length != nrow) return @"";
    return letters;
}

static int is_letter_tile(const unsigned char *buf, size_t W, size_t H, Box box) {
    int inset = box.w / 8;
    if (inset < 2) inset = 2;
    int ink = 0, tot = 0;
    for (int y = box.y + inset; y < box.y + box.h - inset; y += 2) {
        if (y < 0 || y >= (int)H) continue;
        for (int x = box.x + inset; x < box.x + box.w - inset; x += 2) {
            if (x < 0 || x >= (int)W) continue;
            tot++;
            if (dark_px(buf + ((size_t)y * W + x) * 4)) ink++;
        }
    }
    double ratio = tot ? (double)ink / (double)tot : 0;
    if (ratio < 0.012 || ratio > 0.72) return 0;
    int border = 0, samples = 0;
    int step = box.w / 6;
    if (step < 2) step = 2;
    for (int dist = 1; dist <= 4; dist++) {
        for (int x = box.x; x < box.x + box.w; x += step) {
            int yb = box.y - dist;
            int yt = box.y + box.h + dist - 1;
            if (yb < 0 || yt >= (int)H || x < 0 || x >= (int)W) continue;
            samples += 2;
            if (dark_px(buf + ((size_t)yb * W + x) * 4)) border++;
            if (dark_px(buf + ((size_t)yt * W + x) * 4)) border++;
        }
    }
    if (samples > 0 && border * 8 < samples) return 0;
    return 1;
}

static int message_ink(const unsigned char *p) {
    int r = p[0], g = p[1], b = p[2];
    int mx = r > g ? r : g;
    if (b > mx) mx = b;
    int mn = r < g ? r : g;
    if (b < mn) mn = b;
    // White letters, or a colored refusal line such as red "already used".
    return mx > 175 && (mn > 165 || mx - mn > 50);
}

static NSString *ocr_error_band(const unsigned char *buf, size_t W, size_t H, int top) {
    int y0 = top + 8;
    int bandH = (int)(H * 0.13);
    if (bandH < 28) bandH = 28;
    if (bandH > 180) bandH = 180;
    if (y0 < 0) y0 = 0;
    if (y0 + bandH > (int)H) bandH = (int)H - y0;
    if (bandH < 16 || W < 8) return @"";
    size_t bpr = W * 4;
    unsigned char *bandBuf = malloc((size_t)bandH * bpr);
    if (!bandBuf) return @"";
    for (int y = 0; y < bandH; y++) {
        const unsigned char *src = buf + (size_t)(y0 + y) * bpr;
        unsigned char *dst = bandBuf + (size_t)y * bpr;
        for (size_t x = 0; x < W; x++) {
            const unsigned char *p = src + x * 4;
            unsigned char *d = dst + x * 4;
            if (message_ink(p)) d[0] = d[1] = d[2] = 0;
            else d[0] = d[1] = d[2] = 255;
            d[3] = 255;
        }
    }
    CGImageRef band = image_from_buffer(bandBuf, W, (size_t)bandH);
    CGImageRef small = band ? fit_width(band, 900) : NULL;
    NSString *text = ocr_text(small ?: band, NO) ?: @"";
    if (band) CGImageRelease(band);
    if (small) CGImageRelease(small);
    free(bandBuf);
    return text;
}

static void scan_buffer(unsigned char *buf, size_t W, size_t H) {
    CFAbsoluteTime t0 = CFAbsoluteTimeGetCurrent();
    if (!buf || W < 8 || H < 8) {
        emit(@"", @"", 0, 0, 0, @"");
        return;
    }
    size_t bpr = W * 4;

    // The turn line is the white banner under the window chrome. Chat sits lower.
    int headY = (int)(H * 0.012);
    int headH = (int)(H * 0.145);
    if (headY + headH > (int)H) headH = (int)H - headY;
    if (headH < 8) headH = 8;
    static NSString *cachedHeader = nil;
    static unsigned long cachedHeadHash = 0;
    unsigned long headHash = hash_bytes(buf + (size_t)headY * bpr, (int)W, headH, 6);
    NSString *header = cachedHeader ?: @"";
    // The 3D view makes this band change every frame. OCR at most a few times
    // a second, and keep the last turn line in between.
    static CFAbsoluteTime lastHeaderOcr = 0;
    CFAbsoluteTime headerNow = CFAbsoluteTimeGetCurrent();
    if ((headHash != cachedHeadHash || !cachedHeader) && headerNow - lastHeaderOcr > 0.12) {
        lastHeaderOcr = headerNow;
        unsigned char *bandBuf = malloc((size_t)headH * bpr);
        if (bandBuf) {
            memcpy(bandBuf, buf + (size_t)headY * bpr, (size_t)headH * bpr);
            // White banner letters become black on white so the outline does not confuse OCR.
            for (size_t i = 0; i < (size_t)headH * W; i++) {
                unsigned char *p = bandBuf + i * 4;
                if (p[0] > 210 && p[1] > 210 && p[2] > 210) {
                    p[0] = p[1] = p[2] = 0;
                } else {
                    p[0] = p[1] = p[2] = 255;
                }
            }
            CGImageRef band = image_from_buffer(bandBuf, W, (size_t)headH);
            CGImageRef small = band ? fit_width(band, 720) : NULL;
            header = ocr_text(small ?: band, NO) ?: @"";
            if (band) CGImageRelease(band);
            if (small) CGImageRelease(small);
            free(bandBuf);
        }
        cachedHeadHash = headHash;
        cachedHeader = [header copy];
    }

    // The word can sit anywhere on the key screen, not only in a thin top band.
    int y0 = (int)(H * 0.04);
    int y1 = (int)(H * 0.74);
    if (y1 > (int)H) y1 = (int)H;
    if (y1 < y0 + 8) y1 = (int)H;
    int bandH = y1 - y0;
    size_t maskN = W * (size_t)bandH;
    static uint8_t *mask = NULL;
    static uint8_t *seen = NULL;
    static int *stack = NULL;
    static size_t bufCap = 0;
    if (maskN > bufCap || !mask || !seen || !stack) {
        free(mask);
        free(seen);
        free(stack);
        mask = (uint8_t *)malloc(maskN);
        seen = (uint8_t *)malloc(maskN);
        stack = (int *)malloc(sizeof(int) * maskN);
        bufCap = (mask && seen && stack) ? maskN : 0;
    }
    if (!mask || !seen || !stack) {
        emit(@"", header ?: @"", 0, 0, 0, @"");
        return;
    }
    memset(mask, 0, maskN);
    memset(seen, 0, maskN);
    for (int y = y0; y < y1; y++) {
        unsigned char *row = buf + (size_t)y * bpr;
        uint8_t *mrow = mask + (size_t)(y - y0) * W;
        for (size_t x = 0; x < W; x++) {
            if (white_px(row + x * 4)) mrow[x] = 1;
        }
    }

    double scale = (double)W / 900.0;
    if (scale < 0.65) scale = 0.65;
    int minSide = (int)(26 * scale);
    int maxSide = (int)(190 * scale);
    Box boxes[240];
    int nboxes = 0;
    for (int y = y0; y < y1 && nboxes < 240; y++) {
        for (int x = 0; x < (int)W && nboxes < 240; x++) {
            size_t i = (size_t)(y - y0) * W + (size_t)x;
            if (!mask[i] || seen[i]) continue;
            int sp = 0;
            stack[sp++] = (int)i;
            seen[i] = 1;
            int minx = x, maxx = x, miny = y, maxy = y, count = 0;
            while (sp) {
                int cur = stack[--sp];
                int cy = y0 + cur / (int)W;
                int cx = cur % (int)W;
                count++;
                if (cx < minx) minx = cx;
                if (cx > maxx) maxx = cx;
                if (cy < miny) miny = cy;
                if (cy > maxy) maxy = cy;
                const int dirs[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
                for (int d = 0; d < 4; d++) {
                    int nx = cx + dirs[d][0], ny = cy + dirs[d][1];
                    if (nx < 0 || ny < y0 || nx >= (int)W || ny >= y1) continue;
                    size_t ni = (size_t)(ny - y0) * W + (size_t)nx;
                    if (!mask[ni] || seen[ni]) continue;
                    seen[ni] = 1;
                    stack[sp++] = (int)ni;
                }
            }
            int bw = maxx - minx + 1, bh = maxy - miny + 1;
            if (bw < minSide || bh < minSide || bw > maxSide || bh > maxSide) continue;
            if (abs(bw - bh) > bw / 5) continue;
            double fill = (double)count / (double)(bw * bh);
            if (fill < 0.45 || fill > 0.96) continue;
            boxes[nboxes++] = (Box){minx, miny, bw, bh};
        }
    }

    // The counter of O, D, A, P, Q, R, B is its own white blob. Drop blobs inside a tile.
    int keep[240];
    int nkeep = 0;
    for (int i = 0; i < nboxes; i++) {
        int inside = 0;
        for (int j = 0; j < nboxes; j++) {
            if (i != j && contained(boxes[i], boxes[j])) inside = 1;
        }
        if (!inside) keep[nkeep++] = i;
    }

    Box kept[240];
    int nkept = 0;
    for (int i = 0; i < nkeep; i++) {
        if (!is_letter_tile(buf, W, H, boxes[keep[i]])) continue;
        kept[nkept++] = boxes[keep[i]];
    }
    qsort(kept, (size_t)nkept, sizeof(Box), box_cmp);
    if (getenv("LLDEBUG")) {
        fprintf(stderr, "kept %d\n", nkept);
        for (int i = 0; i < nkept; i++) fprintf(stderr, "  %d,%d %dx%d\n", kept[i].x, kept[i].y, kept[i].w, kept[i].h);
    }

    int bestI = 0, bestJ = -1, bestCount = 0;
    double bestScore = -1;
    for (int i = 0; i < nkept; i++) {
        int last = i;
        int count = 1;
        for (int j = i + 1; j < nkept; j++) {
            int dy = abs((kept[j].y + kept[j].h / 2) - (kept[i].y + kept[i].h / 2));
            if (dy > kept[i].h / 2) continue;
            if (abs(kept[j].h - kept[i].h) > kept[i].h / 2) continue;
            if (abs(kept[j].w - kept[i].w) > kept[i].w / 2) continue;
            int gap = kept[j].x - (kept[last].x + kept[last].w);
            if (gap < -(kept[i].w / 4) || gap > (int)(kept[i].w * 1.05)) break;
            count++;
            last = j;
        }
        // A row of letter tiles beats one big speech bubble.
        double score = (double)count * count * kept[i].h * kept[i].w;
        double cx = (kept[i].x + kept[last].x + kept[last].w) / 2.0;
        double off = fabs(cx - (double)W / 2.0) / (double)W;
        score *= (1.15 - off);
        if (score > bestScore) {
            bestScore = score;
            bestCount = count;
            bestI = i;
            bestJ = last;
        }
    }

    Box row[64];
    int nrow = 0;
    if (bestJ >= bestI && bestCount > 0) {
        for (int j = bestI; j <= bestJ && nrow < 64; j++) {
            int dy = abs((kept[j].y + kept[j].h / 2) - (kept[bestI].y + kept[bestI].h / 2));
            if (dy > kept[bestI].h / 2) continue;
            // A tile carries a dark letter. Empty white squares are chrome.
            int ink = 0, tot = 0;
            int inset = kept[j].w / 8;
            if (inset < 2) inset = 2;
            for (int y = kept[j].y + inset; y < kept[j].y + kept[j].h - inset; y += 2) {
                unsigned char *line = buf + (size_t)y * bpr;
                for (int x = kept[j].x + inset; x < kept[j].x + kept[j].w - inset; x += 2) {
                    tot++;
                    if (dark_px(line + x * 4)) ink++;
                }
            }
            double ratio = tot ? (double)ink / (double)tot : 0;
            // I and L are thin. A higher floor drops the I in a prompt like "id".
            if (ratio < 0.012 || ratio > 0.72) continue;
            // Black stroke just outside the white fill. Sample a few pixels out
            // so a thin stroke still counts and the sky behind it does not.
            int border = 0, samples = 0;
            int step = kept[j].w / 6;
            if (step < 2) step = 2;
            for (int dist = 1; dist <= 4; dist += 1) {
                for (int x = kept[j].x; x < kept[j].x + kept[j].w; x += step) {
                    int yb = kept[j].y - dist;
                    int yt = kept[j].y + kept[j].h + dist - 1;
                    if (yb < 0 || yt >= (int)H) continue;
                    samples += 2;
                    if (dark_px(buf + ((size_t)yb * W + x) * 4)) border++;
                    if (dark_px(buf + ((size_t)yt * W + x) * 4)) border++;
                }
            }
            if (samples > 0 && border * 8 < samples) continue;
            row[nrow++] = kept[j];
        }
    }

    static NSString *cachedPrompt = nil;
    static unsigned long cachedTileHash = 0;
    static int cachedFull = 1;
    NSString *prompt = @"";
    int full = 1;
    unsigned long tileHash = 1469598103934665603UL;
    for (int i = 0; i < nrow; i++) {
        tileHash ^= (unsigned long)(row[i].x * 131 + row[i].y * 17 + row[i].w * 3);
        tileHash *= 1099511628211UL;
        for (int y = row[i].y; y < row[i].y + row[i].h; y += 3) {
            const unsigned char *line = buf + (size_t)y * bpr + (size_t)row[i].x * 4;
            for (int x = 0; x < row[i].w; x += 3) {
                tileHash ^= line[x * 4];
                tileHash *= 1099511628211UL;
            }
        }
    }
    if (nrow > 0 && tileHash == cachedTileHash && cachedTileHash != 0) {
        prompt = cachedPrompt ?: @"";
        full = cachedFull;
    } else if (nrow > 0) {
        NSString *letters = read_tiles(buf, W, H, row, nrow) ?: @"";
        if ((int)letters.length == nrow) {
            prompt = letters;
            full = 1;
        } else {
            // A dropped letter would store a different word. Keep the previous complete read.
            prompt = @"";
            full = 0;
        }
        cachedTileHash = tileHash;
        cachedPrompt = [prompt copy];
        cachedFull = full;
    } else {
        cachedTileHash = 0;
        cachedPrompt = @"";
        cachedFull = 1;
        prompt = @"";
        full = 1;
    }

    static NSString *cachedError = nil;
    static CFAbsoluteTime cachedErrorAt = 0;
    static CFAbsoluteTime lastErrorOcr = 0;
    NSString *error = @"";
    if (nrow > 0) {
        int bottom = 0;
        for (int i = 0; i < nrow; i++) {
            int edge = row[i].y + row[i].h;
            if (edge > bottom) bottom = edge;
        }
        CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
        if (now - lastErrorOcr > 0.22) {
            lastErrorOcr = now;
            NSString *text = ocr_error_band(buf, W, H, bottom) ?: @"";
            NSString *low = text.lowercaseString;
            if ([low containsString:@"already"] || [low containsString:@"used"]) {
                cachedError = [text copy];
                cachedErrorAt = now;
            } else if (cachedError && now - cachedErrorAt > 0.45) {
                cachedError = nil;
            }
        }
        if (cachedError && CFAbsoluteTimeGetCurrent() - cachedErrorAt < 2.0) error = cachedError;
    }
    int ms = (int)((CFAbsoluteTimeGetCurrent() - t0) * 1000.0);
    emit(prompt, header ?: @"", full ? nrow : nrow, ms, full, error);
}

static void scan_image(CGImageRef img) {
    if (!img) {
        emit(@"", @"", 0, 0, 0, @"");
        return;
    }
    size_t W = CGImageGetWidth(img);
    size_t H = CGImageGetHeight(img);
    size_t bpr = W * 4;
    unsigned char *buf = calloc(H, bpr);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(buf, W, H, 8, bpr, cs, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(cs);
    if (!ctx || !buf) {
        free(buf);
        CGImageRelease(img);
        emit(@"", @"", 0, 0, 0, @"");
        return;
    }
    CGContextDrawImage(ctx, CGRectMake(0, 0, W, H), img);
    CGContextRelease(ctx);
    CGImageRelease(img);
    scan_buffer(buf, W, H);
    free(buf);
}

static int read_full(void *dst, size_t nbytes) {
    unsigned char *p = dst;
    size_t got = 0;
    while (got < nbytes) {
        ssize_t n = read(STDIN_FILENO, p + got, nbytes - got);
        if (n <= 0) return 0;
        got += (size_t)n;
    }
    return 1;
}

static void read_frames(void) {
    for (;;) {
        uint32_t wh[2];
        if (!read_full(wh, sizeof(wh))) return;
        uint32_t w = wh[0], h = wh[1];
        if (w == 0 || h == 0 || w > 8000 || h > 8000) return;
        size_t nbytes = (size_t)w * h * 4;
        unsigned char *buf = malloc(nbytes);
        if (!buf || !read_full(buf, nbytes)) {
            free(buf);
            return;
        }
        @autoreleasepool {
            scan_buffer(buf, w, h);
        }
        free(buf);
    }
}

int main(int argc, char **argv) {
    @autoreleasepool {
        setvbuf(stdout, NULL, _IOLBF, 0);
        build_templates();
        if (argc > 2 && strcmp(argv[1], "--png") == 0) {
            NSImage *file = [[NSImage alloc] initWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]];
            NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithData:file.TIFFRepresentation];
            if (!rep.CGImage) return 1;
            scan_image(CGImageRetain(rep.CGImage));
            return 0;
        }
        ll_capture = dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
        if (!ll_capture) {
            fprintf(stderr, "capture unavailable\n");
            return 1;
        }
        if (argc > 1 && strcmp(argv[1], "--frames") == 0) {
            read_frames();
            return 0;
        }
        BOOL once = argc > 1 && strcmp(argv[1], "--once") == 0;
        do {
            @autoreleasepool {
                int wid = roblox_window();
                if (!wid) {
                    emit(@"", @"", 0, 0, 0, @"");
                    usleep(300000);
                } else {
                    one_frame(wid);
                    usleep(8000);
                }
            }
        } while (!once);
    }
    return 0;
}
