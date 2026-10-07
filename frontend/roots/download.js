async function download_root_zip(filename, zipdata){
    const zip = new JSZip()
    for(const [name, value] of Object.entries(zipdata))
        zip.file(name, await value, {binary:true})
    const blob = await zip.generateAsync({type:'blob'})
    download_blob(filename, blob)
}

function prepared_companions_for_files(filenames){
    const records = new Map()
    for(const filename of filenames)
        for(const record of GLOBAL.files[filename]?.prepared_companions ?? [])
            records.set(record.output_name, record)
    return [...records.values()]
}

function add_prepared_companions(zipdata, filenames){
    const companions = prepared_companions_for_files(filenames)
    if(!companions.length)
        return
    zipdata['preparation-companions.json'] = JSON.stringify({schema: 1, companions}, null, 2)
    for(const record of companions){
        const source = filenames.map(name => GLOBAL.files[name]).find(
            file => file.preparation?.preparation_id == record.preparation_id,
        )
        zipdata[`preparation-companions/${record.output_name}`] = (async () => {
            await RootSecurity.request('/api/preparation/validate', 'POST', {
                filename: source.name, manifest: source.preparation, companions: [record],
            })
            return await fetch_as_blob(url_for_image(record.output_name))
        })()
    }
}

RootDetectionDownload = class extends BaseDownload{
    static async on_single_item_download_click(event){
        const filename = $(event.target).closest('[filename]').attr('filename')
        const zipdata = this.zipdata_for_file(filename)
        if(!zipdata){
            $('body').toast({message:'No detection result is available for this image.', class:'error'})
            return
        }
        const $button = $(event.currentTarget ?? event.target)
        $button.addClass('loading disabled').attr('aria-busy', 'true')
        try {
            await download_root_zip(`${filename}.detection-results.zip`, zipdata)
        } catch(error) {
            $('body').toast({message:`Detection download failed: ${RootSecurity.error_message(error)}`, class:'error'})
        } finally {
            $button.removeClass('loading disabled').removeAttr('aria-busy')
        }
    }

    static async on_download_all(event){
        if(this.download_in_progress)
            return
        const zipdata = this.zipdata_for_files(Object.keys(GLOBAL.files))
        if(!Object.keys(zipdata).length){
            $('body').toast({message:'No detection results are available to download.', class:'warning'})
            return
        }
        const $button = $(event?.currentTarget ?? event?.target ?? '#detection-download-all')
        this.download_in_progress = true
        $button.addClass('loading disabled').attr('aria-busy', 'true')
        try {
            await download_root_zip('RootDetector-detection-results.zip', zipdata)
        } catch(error) {
            $('body').toast({message:`Detection download failed: ${RootSecurity.error_message(error)}`, class:'error'})
        } finally {
            this.download_in_progress = false
            $button.removeClass('loading disabled').removeAttr('aria-busy')
        }
    }

    //override
    static zipdata_for_file(filename){
        var f                           = GLOBAL.files[filename];
        if(!f.results)
            return undefined;
        
        var zipdata                     = {};
        var segmentation                = f.results.segmentation
        var skeleton                    = f.results.skeleton
        zipdata[`${segmentation.name}`] = segmentation
        zipdata[`${skeleton.name}`]     = skeleton
        zipdata[`statistics.csv`]       = this.csv_data_for_file(filename)
        if(f.preparation)
            zipdata['preparation-manifest.json'] = JSON.stringify({
                schema: 1, preparations: [f.preparation],
            }, null, 2)
        add_prepared_companions(zipdata, [filename])
        return zipdata;
    }

    //override
    static zipdata_for_files(filenames){
        filenames = filenames.filter(filename => !!GLOBAL.files[filename]?.results)
        var zipdata      = super.zipdata_for_files(filenames)
        var combined_csv = ''
        for(var i in filenames){
            var single_csv = this.csv_data_for_file(filenames[i], i==0)
            if(single_csv!=undefined)
                combined_csv += single_csv;
        }
        if(combined_csv.length > 0)
            zipdata['statistics.csv'] = combined_csv;
        const preparations = filenames
            .map(filename => GLOBAL.files[filename]?.preparation)
            .filter(Boolean)
        if(preparations.length)
            zipdata['preparation-manifest.json'] = JSON.stringify({
                schema: 1, preparations: preparations,
            }, null, 2)
        add_prepared_companions(zipdata, filenames)
        return zipdata;
    }

    static csv_data_for_file(filename, header=true){
        var csvtxt = '';
        if(header){
            csvtxt += 'Filename, '
                + '# root pixels, # background pixels, '
                + '# mask pixels, # skeleton pixels, '
                + '# skeleton pixels (<3px width), # skeleton pixels (3-7px width), # skeleton pixels (>7px width),'
                + 'Kimura length'
                + ';\n';
        }
        
        var f = GLOBAL.files[filename]
        if(!f.results)
            return;
        
        var stats = f.results.statistics;
        csvtxt   += [
            filename,
            stats.sum,       stats.sum_negative,
            stats.sum_mask,  stats.sum_skeleton, 
            stats.widths[0], stats.widths[1], stats.widths[2],
            stats.kimura_length,
        ].join(', ')+';\n'

        return csvtxt;
    }
}



RootTrackingDownload = class extends BaseDownload {
    static async on_single_item_download_click(event){
        const $root = $(event.target).closest('[filename0][filename1][filename]')
        const filename = $root.attr('filename')
        const data = GLOBAL.files[$root.attr('filename0')]?.tracking_results?.[$root.attr('filename1')]
        if(!this.is_exportable_result(data)){
            $('body').toast({message:'No tracking result is available for this pair.', class:'warning'})
            return
        }
        const $button = $(event.currentTarget ?? event.target)
        $button.addClass('loading disabled').attr('aria-busy', 'true')
        try {
            const pair = [$root.attr('filename0'), $root.attr('filename1')]
            if(data.run_id)
                pair.push(data.run_id)
            const result = await RootSecurity.request(
                '/compile_tracking_results', 'POST', this.selection_payload([pair]),
            )
            downloadURI(`RootDetector-tracking-${data.run_id ?? filename}.zip`, url_for_image(result))
        } catch(error) {
            $('body').toast({message:`Tracking download failed: ${RootSecurity.error_message(error)}`, class:'error'})
        } finally {
            $button.removeClass('loading disabled').removeAttr('aria-busy')
        }
    }

    static is_exportable_result(result){
        return !!(
            result?.growthmap && result?.segmentation0 && result?.segmentation1
            && result?.statistics && Array.isArray(result?.points0)
            && Array.isArray(result?.points1)
        )
    }

    static selection_payload(file_pairs){
        const names = new Set(file_pairs.flatMap(pair => pair.slice(0, 2)))
        return {
            file_pairs,
            companions: prepared_companions_for_files([...names]),
            preparations: Object.fromEntries(Object.entries(GLOBAL.files)
                .filter(([name, file]) => names.has(name) && !!file.preparation)
                .map(([name, file]) => [name, file.preparation])),
        }
    }

    //override
    static zipdata_for_file(filename){
        var $root     = $(`[filename0][filename1][filename="${filename}"]`)
        if($root.length==0) //should not happen
            return;
        
        var filename0     = $root.attr('filename0')
        var filename1     = $root.attr('filename1')
        var tracking_data = GLOBAL.files[filename0].tracking_results[filename1];
        if(!this.is_exportable_result(tracking_data))
            return;

        var zipdata  = {};
        zipdata[tracking_data.growthmap]     = fetch_as_blob(url_for_image(tracking_data.growthmap))
        zipdata[tracking_data.segmentation0] = fetch_as_blob(url_for_image(tracking_data.segmentation0))
        zipdata[tracking_data.segmentation1] = fetch_as_blob(url_for_image(tracking_data.segmentation1))
        var jsondata = {
            filename0 : filename0,
            filename1 : filename1,
            points0   : tracking_data.points0,
            points1   : tracking_data.points1,
            n_matched_points   : tracking_data.n_matched_points,
            tracking_model     : tracking_data.tracking_model,
            segmentation_model : tracking_data.segmentation_model,
            tracking_matcher   : tracking_data.tracking_matcher,
            run_id             : tracking_data.run_id,
            run_profile        : tracking_data.run_profile,
            match_device       : tracking_data.match_device,
            exclusion_mask_policy : tracking_data.exclusion_mask_policy,
            exclusion_masks       : tracking_data.exclusion_masks,
        }
        zipdata[`${filename0}.${filename1}.json`] = JSON.stringify(jsondata);
        zipdata[`${filename0}.${filename1}.csv`]  = this.csv_data_statistics(filename0, filename1)
        zipdata['tracking-results-manifest.json'] = JSON.stringify({
            tracking_csv_schema: 2,
            exclusion_mask_coordinate_system: 'observation1',
            exclusion_mask_policy: tracking_data.exclusion_mask_policy,
            tracking_matcher: tracking_data.tracking_matcher,
            run_id: tracking_data.run_id,
            run_profile: tracking_data.run_profile,
            migration_warning: 'Tracking CSV files exported by RootDetector before schema 2 may have background, mask, same, decay, and growth values under incorrect headers. Re-export those analyses before comparing or aggregating them.',
        }, null, 2)
        const preparations = [filename0, filename1]
            .map(filename => GLOBAL.files[filename]?.preparation)
            .filter(Boolean)
        if(preparations.length)
            zipdata['preparation-manifest.json'] = JSON.stringify({
                schema: 1, preparations: preparations,
            }, null, 2)
        return zipdata;
    }

    static async on_download_all(event) {
        if(this.download_in_progress)
            return
        const filenames  = Object.keys(GLOBAL.files)
        const file_pairs = []
        for(const filename0 of filenames) {
            const tracking_results = GLOBAL.files[filename0].tracking_results
            if( tracking_results == undefined )
                continue;
            
            for(const filename1 of Object.keys(tracking_results)){
                const selected = tracking_results[filename1]
                if(this.is_exportable_result(selected)){
                    file_pairs.push(selected.run_id
                        ? [filename0, filename1, selected.run_id]
                        : [filename0, filename1])
                }
            }
        }
        if(!file_pairs.length){
            $('body').toast({message:'No tracking results are available to download.', class:'warning'})
            return
        }
        const $button = $(event?.currentTarget ?? event?.target ?? '#tracking-download-all')
        this.download_in_progress = true
        $button.addClass('loading disabled').attr('aria-busy', 'true')
        try {
            const result = await RootSecurity.request(
                '/compile_tracking_results',
                'POST',
                this.selection_payload(file_pairs),
            )
            downloadURI('RootDetector-tracking-results.zip', url_for_image(result))
        } catch(error) {
            $('body').toast({message:`Tracking download failed: ${RootSecurity.error_message(error)}`, class:'error'})
        } finally {
            this.download_in_progress = false
            $button.removeClass('loading disabled').removeAttr('aria-busy')
        }
    }


    static csv_data_statistics(filename0, filename1, include_header=true){
        const result = GLOBAL.files[filename0].tracking_results[filename1]
        const stats  = result.statistics ?? {};
        const status_map = {
            true                : 'OK',
            false               : 'WARNING: No matching roots found',
            'TOO_MANY_ROOTS'    : 'SKIPPED: Too many roots'
        }

        const header = [
            'Filename 1',           'Filename 2', 
            'same pixels',          'decay pixels',          'growth pixels',
            'background pixels',    'mask pixels',
            'same skeleton pixels', 'decay skeleton pixels', 'growth skeleton pixels',
            'same kimura length',   'decay kimura length',   'growth kimura length',
            'status',
        ]
        const data   = [
            filename0,         filename1,    
            stats.sum_same,    stats.sum_decay,    stats.sum_growth,
            stats.sum_negative,stats.sum_exmask,
            stats.sum_same_sk, stats.sum_decay_sk, stats.sum_growth_sk,
            stats.kimura_same, stats.kimura_decay, stats.kimura_growth,
            status_map[result.success],
        ]

        //sanity check
        if(header.length != data.length){
            console.error('CSV data length mismatch:', header, data)
            $('body').toast({message:'CSV data length mismatch', class:'error'})
            return;
        }

        const csv_cell = value => {
            const text = value == undefined ? '' : String(value)
            return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
        }
        const csv_row = values => values.map(csv_cell).join(',') + '\r\n'
        return (include_header ? csv_row(header) : '') + csv_row(data)
    }
}
