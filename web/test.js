let btn = document.querySelector("#btn");
btn.addEventListener("click", sendData);

async function sendData(){
            let log=document.querySelector("#log").value;
            let passw=document.querySelector("#passw").value;
            await eel.loggy(log, passw);
}

function openTag(evt, cityName) {
    var i, tabcontent, tablinks;

    tabcontent = document.getElementsByClassName("tabcontent");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }

    tablinks = document.getElementsByClassName("tablinks");
    for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }

    document.getElementById(cityName).style.display = "block";
    evt.currentTarget.className += " active";
}

//sendData()

//async function call(){
//            await eel.pyt_in_js("Hi");
//            }
//call()