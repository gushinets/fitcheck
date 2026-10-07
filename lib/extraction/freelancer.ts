export function isFreelancerProjectUrl(url: URL) {
  return (
    (url.hostname === "www.freelancer.com" || url.hostname === "freelancer.com") &&
    /^\/projects\/[^/]+\/[^/]+/.test(url.pathname)
  )
}
