import { useState, useRef, useEffect, memo, useCallback } from 'react';
import { StreamingPlayer } from '@/components/streaming';
import './StreamingPlayerTest.css';

/**
 * Extract YouTube video ID from various URL formats
 */
function extractYouTubeId(url: string): string | null {
    const patterns = [
        /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
        /^([a-zA-Z0-9_-]{11})$/, // Just the ID
    ];

    for (const pattern of patterns) {
        const match = url.match(pattern);
        if (match?.[1]) return match[1];
    }
    return null;
}

/**
 * StreamingPlayerTest - A test page for the streaming player
 * Allows testing videos with custom referrer headers via proxy
 * Also supports local file upload and YouTube videos
 */
const StreamingPlayerTest = memo(function StreamingPlayerTest() {
    const [videoUrl, setVideoUrl] = useState('');
    const [referrerUrl, setReferrerUrl] = useState('');
    const [activeUrl, setActiveUrl] = useState<string | null>(null);
    const [useProxy, setUseProxy] = useState(true);
    const [proxyUrl, setProxyUrl] = useState('http://localhost:4000');
    const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
    const [sourceType, setSourceType] = useState<'url' | 'file' | 'youtube'>('url');
    const [youtubeId, setYoutubeId] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const blobUrlRef = useRef<string | null>(null);

    // Cleanup blob URL on unmount
    useEffect(() => {
        return () => {
            if (blobUrlRef.current) {
                URL.revokeObjectURL(blobUrlRef.current);
            }
        };
    }, []);

    const handleLoadVideo = useCallback(() => {
        if (!videoUrl.trim()) return;

        const trimmedUrl = videoUrl.trim();

        // Check if it's a YouTube URL
        const ytId = extractYouTubeId(trimmedUrl);
        if (ytId) {
            setYoutubeId(ytId);
            setSourceType('youtube');
            setActiveUrl(null); // Clear native player URL
            return;
        }

        // Regular video URL
        let finalUrl = trimmedUrl;

        // If using proxy, construct appropriate proxy URL
        if (useProxy) {
            const isHls = trimmedUrl.includes('.m3u8');
            const endpoint = isHls ? '/hls' : '/proxy';

            const params = new URLSearchParams({
                url: trimmedUrl,
            });

            // Add referer if provided
            if (referrerUrl.trim()) {
                params.set('referer', referrerUrl.trim());
            }

            finalUrl = `${proxyUrl}${endpoint}?${params.toString()}`;
        }

        setYoutubeId(null);
        setSourceType('url');
        setActiveUrl(finalUrl);
    }, [videoUrl, useProxy, referrerUrl, proxyUrl]);

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        // Cleanup previous blob URL
        if (blobUrlRef.current) {
            URL.revokeObjectURL(blobUrlRef.current);
        }

        // Create new blob URL
        const blobUrl = URL.createObjectURL(file);
        blobUrlRef.current = blobUrl;

        setUploadedFileName(file.name);
        setSourceType('file');
        setActiveUrl(blobUrl);
    };

    const handleClear = () => {
        // Cleanup blob URL if exists
        if (blobUrlRef.current) {
            URL.revokeObjectURL(blobUrlRef.current);
            blobUrlRef.current = null;
        }

        setActiveUrl(null);
        setVideoUrl('');
        setReferrerUrl('');
        setUploadedFileName(null);
        setYoutubeId(null);
        setSourceType('url');

        // Reset file input
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    return (
        <div className="spt-container">
            <header className="spt-header">
                <h1 className="spt-title">🎬 Streaming Player Test</h1>
                <p className="spt-subtitle">Test any video URL with custom referrer support</p>
            </header>

            {/* Input Section */}
            <div className="spt-input-section">
                {/* File Upload */}
                <div className="spt-input-group">
                    <label className="spt-label">
                        <span className="spt-label-icon">📁</span>
                        Upload Local Video File
                    </label>
                    <div className="spt-file-upload">
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept="video/*,.mp4,.webm,.ogg,.m3u8,.mkv,.avi,.mov"
                            onChange={handleFileUpload}
                            className="spt-file-input"
                            id="video-file-input"
                        />
                        <label htmlFor="video-file-input" className="spt-file-label">
                            <span className="spt-file-icon">📤</span>
                            <span className="spt-file-text">
                                {uploadedFileName || 'Click to select or drag & drop a video file'}
                            </span>
                        </label>
                    </div>
                    {uploadedFileName && (
                        <span className="spt-hint spt-hint-success">✓ File loaded: {uploadedFileName}</span>
                    )}
                </div>

                <div className="spt-divider">
                    <span>OR</span>
                </div>

                {/* URL Input */}
                <div className="spt-input-group">
                    <label className="spt-label">
                        <span className="spt-label-icon">🔗</span>
                        Video URL (MP4, M3U8, etc.)
                    </label>
                    <input
                        type="text"
                        className="spt-input"
                        placeholder="https://example.com/video.m3u8?token=..."
                        value={videoUrl}
                        onChange={(e) => setVideoUrl(e.target.value)}
                    />
                </div>

                <div className="spt-input-group">
                    <label className="spt-label">
                        <span className="spt-label-icon">📄</span>
                        Referrer Page URL (Optional)
                    </label>
                    <input
                        type="text"
                        className="spt-input"
                        placeholder="https://appx-play.akamai.net.in"
                        value={referrerUrl}
                        onChange={(e) => setReferrerUrl(e.target.value)}
                    />
                    <span className="spt-hint">For protected videos that require a specific referrer header</span>
                </div>

                <div className="spt-options">
                    <label className="spt-checkbox-label">
                        <input
                            type="checkbox"
                            checked={useProxy}
                            onChange={(e) => setUseProxy(e.target.checked)}
                        />
                        <span>Use Proxy Server (for CORS/Referrer bypass)</span>
                    </label>

                    {useProxy && (
                        <div className="spt-proxy-url">
                            <label className="spt-label-small">Proxy Server URL:</label>
                            <input
                                type="text"
                                className="spt-input spt-input-small"
                                value={proxyUrl}
                                onChange={(e) => setProxyUrl(e.target.value)}
                                placeholder="http://localhost:4000"
                            />
                        </div>
                    )}
                </div>

                <div className="spt-actions">
                    <button
                        className="spt-btn spt-btn-primary"
                        onClick={handleLoadVideo}
                        disabled={!videoUrl.trim()}
                    >
                        ▶ Load Video
                    </button>
                    <button className="spt-btn spt-btn-secondary" onClick={handleClear}>
                        ✕ Clear
                    </button>
                </div>
            </div>

            {/* Player Section - Native Player */}
            {activeUrl && sourceType !== 'youtube' && (
                <div className="spt-player-section">
                    <div className="spt-player-info">
                        <span className={`spt-badge ${sourceType === 'file' ? 'spt-badge-file' : ''}`}>
                            {sourceType === 'file' ? '📁 Local File' : 'Now Playing'}
                        </span>
                        <span className="spt-url-preview">
                            {sourceType === 'file' ? uploadedFileName : (videoUrl.substring(0, 60) + '...')}
                        </span>
                    </div>
                    <div className="spt-player-wrapper">
                        <StreamingPlayer
                            videoUrl={activeUrl}
                            title="Test Video"
                            showSpeedControl={true}
                            showKeyboardShortcuts={true}
                            enablePiP={true}
                            onError={(error) => console.error('Player error:', error)}
                        />
                    </div>
                </div>
            )}

            {/* Player Section - YouTube Embed */}
            {sourceType === 'youtube' && youtubeId && (
                <div className="spt-player-section">
                    <div className="spt-player-info">
                        <span className="spt-badge spt-badge-youtube">
                            ▶ YouTube
                        </span>
                        <span className="spt-url-preview">
                            {videoUrl.substring(0, 60)}...
                        </span>
                    </div>
                    <div className="spt-player-wrapper spt-youtube-wrapper">
                        <iframe
                            src={`https://www.youtube.com/embed/${youtubeId}?autoplay=1&rel=0&modestbranding=1`}
                            title="YouTube Video Player"
                            frameBorder="0"
                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                            allowFullScreen
                            className="spt-youtube-iframe"
                        />
                    </div>
                </div>
            )}

            {/* Instructions */}
            <div className="spt-instructions">
                <h3>📋 Instructions</h3>
                <ol>
                    <li>Paste your video URL (supports MP4, WebM, HLS .m3u8)</li>
                    <li>If the video requires a referrer header (like ClassX), add the referrer page URL</li>
                    <li>Make sure the proxy server is running if using protected videos</li>
                    <li>Click "Load Video" to start playback</li>
                </ol>

                <div className="spt-example">
                    <h4>Example for ClassX Videos:</h4>
                    <pre>
                        Video URL: https://transcoded-videos.classx.co.in/videos/.../master.m3u8?edge-cache-token=...
                        Referrer:  https://appx-play.akamai.net.in
                    </pre>
                </div>

                <div className="spt-proxy-info">
                    <h4>🖥️ Start Proxy Server</h4>
                    <code>node streaming-reference/server.js</code>
                    <p>The proxy server bypasses CORS and adds the referrer header for protected videos.</p>
                </div>
            </div>
        </div>
    );
});

export default StreamingPlayerTest;
