function processTodayAuto() {
  var today = new Date();
  const hour = today.getHours(); // 현재 시간 (0~23)
  var min = today.getMinutes();

  // ✅ 10:10 ~ 21:59 실행
  if ((hour > 10 || (hour === 10 && min >= 10)) && hour < 21) {
    const rowConfig = {
      startRow: 3,
      endRow: 68,// 별관 디럭스 (루시드엠)
      freeStartRow: 100, // 미배정(1)
      freeEndRow: 117    // 미배정(18)
      };

    process(today, rowConfig)
  }

  // ✅ 12:10 ~ 21:59 실행
  if ((hour > 12 || (hour === 12 && min >= 10)) && hour < 22) {
    const startRow = 100; // 미배정(1)
    const endRow = 117; //  미배정(18)
    partyGuideInRange(startRow, endRow)
  }

}

function process(date, rowConfig) {
  // 날짜를 YYYY-MM-DD 포맷으로 변경한다
  function formatDate(date) {
    var d = new Date(date),
      month = '' + (d.getMonth() + 1),
      day = '' + d.getDate(),
      year = d.getFullYear();


    if (month.length < 2)
      month = '0' + month;
    if (day.length < 2)
      day = '0' + day;


    return [year, month, day].join('-');
  }


  var startDateTime = formatDate(date) + "T01%3A03%3A09.198Z";
  var endDateTime = formatDate(date) + "T01%3A03%3A09.198Z";


  // URL 업데이트
  var url = "https://partner.booking.naver.com/api/businesses/819409/bookings?bizItemTypes=STANDARD&bookingStatusCodes=&dateDropdownType=TODAY&dateFilter=USEDATE&endDateTime=" + endDateTime + "&maxDays=31&nPayChargedStatusCodes=&orderBy=&orderByStartDate=ASC&paymentStatusCodes=&searchValue=&searchValueCode=USER_NAME&startDateTime=" + startDateTime + "&page=0&size=200&noCache=1694307842200";

  console.log(url)


  var options = {
    method: 'GET',
    headers: {
      'Accept': '*/*',
      'Accept-Encoding': 'gzip, deflate, br',
      'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
      'Referer': 'https://partner.booking.naver.com/bizes/819409/booking-list-view',
      'Sec-Ch-Ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
      'Sec-Ch-Ua-Mobile': '?0',
      'Sec-Ch-Ua-Platform': '"macOS"',
      'Sec-Fetch-Dest': 'empty',
      'Sec-Fetch-Mode': 'cors',
      'Sec-Fetch-Site': 'same-origin',
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
      'Cookie': 'NACT=1; NAC=omaWBggZmKe0A; NNB=N6KW6QVASG4GO; NFS=2; nid_inf=351543061; NID_AUT=BajoX5x7B1w/4704Wk3q6WRgjBFIaRZX2ZuW0Zzm3M/2qNPwIKmpixyPSSoTa6aw; NID_JKL=8TawxzD5kDxI9Zdd44kzJCzCjMoJPD4+wO9wiIuXHsk=; NID_SES=AAAB3w53XTMt/9T/u602KjF0em0gFfHZFb1QBV+btZYFx8cUXDZRPpkev0CrfwsX5s54P7fbv1DNnDgpyR+HlWKTBd8HURHEpOjw9umIZAuh6klNNJ9/LWaxIvlPCcNsOl9MwFmySqawydiYzgiIhQ/kLK0ZPGqXakFbOpuyYRy4QmL4WWNj/PbQTyXnRa+36VI1cIj3p7viNVY5sIjeP/vIXtB5WGRv6ko2JQLXvVduGygR9u3zENlmg7EcpND5R2GsQ5rWog2eO/0DDu6q0oIKEel18DHtfWveuNigxdSMahZ+ROk0nLTmI+Oon+Bh0YI8uXuicMZqzRnFoCl/tF28JJNKfBnlaW/AVm7yUktwNY+rPFwFJ/o1lyzgfkKa7ob37w4E3cf+oCHuBcyzDKKSFHgQ5Qp/LEsIV7luZNPuH9P9FSQ4btxsanLHIfJhhXH+VtBFhogzJbm7OJ72V17WgcKNyjh2gtg4Cex3H/PLU332zyWA6DfyJ8FHMiiu61Nq3Rk5TlwvfwG8a/8a7yhxXII3CRCdfaAmjf+3N/oxO8SUoqrjZejFusA+bh33Fkl1aedvRPmIR2eIQmgKvgDQzfMmjLD4gpvZmSSEXtW33jUm3MmJ0BjGwAloSE6vaylmNA==; SRT30=1743334386; BUC=I2eiWqhAelm-T3dkz8xro7YkBSJg3RjxH2tJ8TxLWfY='
      //'NNB=HT7EARW6DTQGI; nx_ssl=2; nid_inf=-1570933744; NID_AUT=K3qDSqlga2+m1SlMBr8q0bwIfsTjqG97xWpVk+xMY0Z7UgJkQIMoO63pFhpIhwDY; NID_JKL=ne8/ChcuGUepzQJH6VCagFH74pFjpLS/+wiYHiQ0rpY=; NV_WETR_LAST_ACCESS_RGN_M="MTQxMTAyNTM="; NV_WETR_LOCATION_RGN_M="MTQxMTAyNTM="; ASID=d322fc780000018a277f45430000005d; page_uid=iMYlYsprvh8ssOX04f0ssssssV4-213600; ba_access_token=bgv7fvHy6arUVsYYBYFwExBqUG%2BQfEv8zqGmZVOd6OyPIfXZvgndb29VbNjbIfrrsLBCKuc4UinwcdydQXS0rowJlVasRb5UdikhlqJrJ793VLf6yKfrDVcD%2Fs2ANSwO7tLGS%2BBbuFzkKejL%2FTxpcIeEsJ3XRIRncYBJZuKk%2Fduoz%2BvijJgn8BCBMegr3ByIQahV8ghyid165F%2FqwRBZD7PqWV3qwN0BvsZFDUNRzdTRS2p5BKvVSUM%2FZ2TjIHBxcn8Rn31tcvMGpsEXqRx2Z687S4BQx%2FXTt%2BXsWwYRfXomNCjZso9rl6u%2BFfDysXfzY2BUNMT%2BTvKQ6%2BV%2B8o6ih5fY3hvSeK%2B8gvZOvXwEBeU%3D; NID_SES=AAAB0QleqJc113m3U1ooegERPoQ2WS61bVs2AH17O5yRiiY0eHhwdvm9s3iok62wm99DE7e47ryN6Lyv14arV/0mWN84oIMuXbMeiq7LgByfCEKnqyLODuv+cgJFJe3CEpua8fDRkOGDo5iFU1oywXzd4PMhBpe8MnJ4KXoI2BBayyuWtDg8SnPTneL4TNvWDWebW5/lbTrFh5Tik6nsQiAz1FPmgJNCI2aeFCpykpwhI021q2QpHa1cRewEGlKSW9XOAY6N9x4Dm3xGexzReCREzFQytnoU2xoA8L1IUS7RFetunHMW/qOU+D0F+X/TZwybqFvl+Tkh2kZRSNvKXv6LWpzNoPqeomfQcxWkIkvFh6Z37UE/OR/2LWF64tEUxPcLpeu2G7krSB8F56QTSwRdp81/nakvdE4syxY7Gd4G3jNwJXbdYG3IcWS3gEbOHY/7mbLXCR8g1HJHE0ZBL6WOVmlunSNBiZ3vWxJHtzbtfUFi56ip66egDIIswF8MIJibPIwSOCSTJACKSXwt2yY98+1V5QFP0Cr74EX37SIlDyK7U1gKpXCfAbAJgEC9IDVu8jyvm+iszzEL30j26K0nM2q/ZG67Q9rmkLAMhFH7rqcG9l9rnLO4CSnS73Z+ZvJf3w==; csrf_token=0529d7445b89d611feb02feade78164860e97aa732d904129e19bb4a1e8606cc7eacfaa664ee8ead94ef12730c40512e79c05e16496e9e65e5c5c2c184e8cf1c' // 여기에 Cookie 정보를 넣어주세요.
     
    },
    muteHttpExceptions: true,
    followRedirects: true
  };


  var response = UrlFetchApp.fetch(url, options);
  var responseText = response.getContentText();


    try {
    var data = JSON.parse(responseText);

    var sheetName = getdateSheetName2(date);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) {
      Logger.log(sheetName + "이라는 이름의 시트를 찾을 수 없습니다.");
      return;
    }

    Logger.log(sheet.getSheetName());

    var columnIndex = getDateChannelNameColumn(sheet, date);
    var NaverBizItemIdColumn = 4;
    var ReservationCountColumn = 5;

    var startRow = rowConfig.startRow;
    var endRow = rowConfig.endRow;
    var startingUnprocessedRow = getNextUnprocessedRow(sheet, rowConfig.freeStartRow, rowConfig.freeEndRow, columnIndex);

    var now = new Date();
    var twentyMinutesAgo = new Date(now.getTime() - 20 * 60 * 1000); // 20분전

    // confirmData: 20분 이내 등록 + 오늘 퇴실 아님 + 컨펌 상태
    var confirmData = data.filter(item => {
      const isConfirmed = item.bookingStatusCode === 'RC03';
      const isNotTodayCheckout = formatDate(new Date(item.endDate)) !== formatDate(date);
      const confirmedDateTime = new Date(item.confirmedDateTime);
      return isConfirmed && isNotTodayCheckout && confirmedDateTime >= twentyMinutesAgo;
    });

    var cancelData = data.filter(item => {
      const isCanceled = item.bookingStatusCode === 'RC04';
      const isNotTodayCheckout = formatDate(new Date(item.endDate)) !== formatDate(date);
      const confirmedDateTime = new Date(item.confirmedDateTime);
      return isCanceled && isNotTodayCheckout && confirmedDateTime >= now;
    });

    Logger.log("컨펌데이터 갯수 : " + confirmData.length);
    Logger.log("캔슬데이터 갯수 : " + cancelData.length);

    // 1. flag 초기화
    for (var i = 0; i < confirmData.length; i++) {
      confirmData[i].flag = false;
    }

    // 2. 미배정과 파티 제외 영역(3~68행)에서 중복 제거
    for (var row = startRow; row <= endRow; row++) {
      var cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      if (cellPhone) {
        for (var j = 0; j < confirmData.length; j++) {
          if (cellPhone == confirmData[j].phone) {
            Logger.log("시트에 이미 배정된 예약자 (미배정 제외): " + confirmData[j].name);
            confirmData[j].flag = true;
            break;
          }
        }
      }
    }

    // 3. 기존 미배정 영역(85~100행)에서도 중복 제거
    for (var row = rowConfig.freeStartRow; row <= rowConfig.freeEndRow; row++) {
      var cellPhone = sheet.getRange(row, columnIndex + 1).getValue();
      if (!cellPhone) continue;

      for (var j = 0; j < confirmData.length; j++) {
        if (cellPhone == confirmData[j].phone) {
          Logger.log("미배정 영역에 이미 존재하는 예약자 (중복 제외): " + confirmData[j].name);
          confirmData[j].flag = true;
          break;
        }
      }
    }



    // 4. flag가 false인 데이터만 미배정으로 입력
    for (var i = 0; i < confirmData.length; i++) {
      if (!confirmData[i].flag) {
        var userInfo = fetchUserInfo(String(confirmData[i].userId));

        sheet.getRange(startingUnprocessedRow, columnIndex).setValue(confirmData[i].name + "(" + userInfo + ")");
        sheet.getRange(startingUnprocessedRow, columnIndex + 1).setValue("'" + confirmData[i].phone);

        var peopleNumber = sheet.getRange(startingUnprocessedRow, ReservationCountColumn).getValue();
        if (confirmData[i].bookingOptionJson && confirmData[i].bookingOptionJson.length > 0) {
          for (let j = 0; j < confirmData[i].bookingOptionJson.length; j++) {
            if (confirmData[i].bookingOptionJson[j].bookingCount === 1) {
              peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
            } else {
              peopleNumber = confirmData[i].bookingOptionJson[j].bookingCount;
            }
            break;
          }
        } else {
          const isSingle = confirmData[i].bookingCount == 1;
          if (isSingle) {
            peopleNumber = getMaxPeopleByRoomId(confirmData[i].bizItemId)
          } else {
            peopleNumber = confirmData[i].bookingCount;
          }
        }

        var existingValue3 = sheet.getRange(startingUnprocessedRow, columnIndex + 3).getValue();
        if (!existingValue3) {
        const isDormitory = [4779029, 4779028].includes(confirmData[i].bizItemId)
        if (isDormitory) {
          const sexText = confirmData[i].bizItemId == 4779029 ? "여" : "남"
          sheet.getRange(startingUnprocessedRow, columnIndex + 3).setValue(sexText + peopleNumber);
        } else {
          sheet.getRange(startingUnprocessedRow, columnIndex + 3).setValue(userInfo.slice(-1) + peopleNumber);
        }  
      }

        var existingValue4 = sheet.getRange(startingUnprocessedRow, columnIndex + 4).getValue();
        if (!existingValue4) {
          sheet.getRange(startingUnprocessedRow, columnIndex + 4).setValue(
            confirmData[i].bookingCount + " (" + getRoomName(confirmData[i].bizItemId) + ")"
          );
        }

        sheet.getRange(startingUnprocessedRow, columnIndex).setHorizontalAlignment('center').setVerticalAlignment('middle');
        sheet.getRange(startingUnprocessedRow, columnIndex + 1).setHorizontalAlignment('center').setVerticalAlignment('middle');
        sheet.getRange(startingUnprocessedRow, columnIndex + 3).setHorizontalAlignment('center').setVerticalAlignment('middle');

        startingUnprocessedRow++;
      }
    }

  } catch (e) {
    Logger.log('JSON 파싱 오류: ' + e);
  }
}

// 어제 날짜 기준 시트명 구하기
function getdateSheetName2(date) {
  var month = (date.getMonth() + 1).toString();
  if (month.length === 1) month = '0' + month;
  var year = date.getFullYear().toString();
  return year + month; // 예: 202308
}

function getRoomName(bizItemId) {
  let roomType = "";
  switch (String(bizItemId)) {
    case "4779029":
    case "4779028":
      roomType = "도미";
      break;
    case "4779035":
      roomType = "스위트";
      break;
    case "4779024":
      roomType = "더블";
      break;
    case "4779031":
      roomType = "더블 스파";
      break;
    case "4779030":
      roomType = "트윈 스파";
      break;
    case "4891205":
      roomType = "별관 독채트윈룸"
      break;
    case "6579700":
      roomType = "별관 더블룸";
      break;
    case "4893072":
      roomType = "별관 트리플룸";
      break;
    case "4856805":
      roomType = "별관 독채";
      break;
    case "4887643":
      roomType = "별관 디럭스룸";
      break;
    
    case "4779014":
    case "4779030":
    case "4779014":
    case "4779030":
      roomType = "트윈";
      break;
      
    default:
      roomType = "방타입" + bizItemId;
      break;
  }
  return roomType;
}

function getNextUnprocessedRow(sheet, startRow, endRow, columnIndex) {
  for (var row = startRow; row <= endRow; row++) {
    var cellValue = sheet.getRange(row, columnIndex).getValue();
    if (!cellValue) {
      return row;
    }
  }
  return endRow + 1; // 모두 차있으면 endRow 다음 줄 반환
}
