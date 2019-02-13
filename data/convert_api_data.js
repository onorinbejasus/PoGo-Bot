const fs = require('fs')
  , _ = require("lodash")
  , old_api = require("./base_stats")
  , new_api = require("./pokemon_stats.json");


let new_data = _.cloneDeep(old_api);

new_api.forEach(p=>{
  let id = _.padStart(p.pokemon_id, 3, '0');

  if(!new_data[`${id}_`]) {
    console.log(id);
    return;
  }

  new_data[`${id}_`]["attack"] = p["base_attack"];
  new_data[`${id}_`]["defense"] = p["base_defense"];
  new_data[`${id}_`]["stamina"] = p["base_stamina"];
});

let json = JSON.stringify(new_data);
fs.writeFile('./base_stats_revised.json', json, 'utf8', err=>{
  if(err) {
    console.log(err);
  }
});
