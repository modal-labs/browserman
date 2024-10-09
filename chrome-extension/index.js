document
  .getElementById('capture-btn')
  .addEventListener('click', async (event) => {
    const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const cookies = await chrome.cookies.getAll({url: activeTab.url});
    console.log(cookies);

    const payload = {
      url: activeTab.url,
      cookies: cookies,
    };
    console.log(payload);

    const target = document.getElementById("target").value;
    const request = new Request(target, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    const response = await fetch(request);
    console.log(response.status);
  });
