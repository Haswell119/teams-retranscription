// Hansard is a notetaker. It has no face, and it must never publish video.
//
// Clicking the pre-join camera toggle is not a guarantee: the selector depends on the
// Teams build and on the interface language, the attribute that says whether the toggle
// is on has changed shape between builds, and Chromium is started with
// --use-fake-device-for-media-stream, so a missed click means joining with a synthetic
// camera feed that every participant can see.
//
// This removes the camera from the page's world instead. No video track can be produced,
// whatever the interface does, so Teams shows the notetaker as camera-off because it is.
(() => {
  const devices = navigator.mediaDevices;
  if (!devices) {
    return;
  }

  const withoutVideo = (constraints) => {
    if (!constraints || typeof constraints !== 'object') {
      return constraints;
    }
    const { video, ...rest } = constraints;
    return rest;
  };

  const wantsOnlyVideo = (constraints) =>
    Boolean(constraints && typeof constraints === 'object' && constraints.video && !constraints.audio);

  const refuse = () => {
    const error = new DOMException('camera disabled by the notetaker', 'NotFoundError');
    return Promise.reject(error);
  };

  const originalGetUserMedia = devices.getUserMedia;
  if (typeof originalGetUserMedia === 'function') {
    devices.getUserMedia = function (constraints) {
      if (wantsOnlyVideo(constraints)) {
        return refuse();
      }
      return originalGetUserMedia.call(this, withoutVideo(constraints));
    };
  }

  const originalEnumerate = devices.enumerateDevices;
  if (typeof originalEnumerate === 'function') {
    devices.enumerateDevices = function () {
      return originalEnumerate
        .call(this)
        .then((found) => found.filter((device) => device.kind !== 'videoinput'));
    };
  }

  const legacy = navigator.getUserMedia;
  if (typeof legacy === 'function') {
    navigator.getUserMedia = function (constraints, onSuccess, onError) {
      if (wantsOnlyVideo(constraints)) {
        if (typeof onError === 'function') {
          onError(new DOMException('camera disabled by the notetaker', 'NotFoundError'));
        }
        return undefined;
      }
      return legacy.call(this, withoutVideo(constraints), onSuccess, onError);
    };
  }
})();
