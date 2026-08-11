// RootDetector-specific hardening for the shared base helper.
fetch_as_blob = async function(url){
    const response = await fetch(url)
    if(!response.ok)
        throw new Error(`Request failed (${response.status}) while loading ${url}`)
    return await response.blob()
}
