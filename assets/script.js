function toggleHeader(objectId) {
    var hl2 = document.getElementById(objectId+"_hl2");
    var snp = document.getElementById(objectId+"_snp");
    var msg = document.getElementById(objectId+"_msg");

    if (hl2.style.display == "none") {
        snp.style.display = "none";
        hl2.style.display = "";
        msg.style.display = "";
    } else {
        hl2.style.display = "none";
        msg.style.display = "none";
        snp.style.display = "";
    }
}

function uncollapse(objectId, first, last) {
    var collapsedDiv = document.getElementById(objectId);
    collapsedDiv.style.display="none";
    for (var i=first; i<=last; i++)
      document.getElementById("mp_"+i).style.display="";   
}